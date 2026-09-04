"""Take an Organic Maps export out of the Downloads junk drawer and into a versioned copy.

The phone's recorded track is the sole source for several journey legs — the 2026-07-26
Sozopol legs and the 2026-07-17 evening return among them — and until now the only copy sat
in `~/Downloads/newmi/My Places (2).kmz`, a Syncthing mirror of the phone's `Download/`
folder, outside the track corpus and outside anything that backs the corpus up. It was
carried as an open item in `journey/TODO.md` for three weeks.

This moves each phone's export into `<data>/../phone/<phone>.kml` (`newmi.kml`,
`pixel.kml`) — its own git repository, kept
**out** of `~/solveig`'s index, because that repository's working tree is served at
`https://solveig.oslo.no/solveig/` and 269 637 second-by-second personal positions are not
the boat's semi-public track. `tracks/` is already gitignored by the parent, so a repository
nested there is invisible to it.

## Why the KML and not the KMZ

A KMZ is a zip, and git cannot delta one: two consecutive real exports cost 5.25 MB
committed as `.kmz` and 2.97 MB committed as the unpacked `.kml`, the former being simply
the sum of the two files. The wrapper is not even reproducible — `My Places.kmz` and
`My Places (1).kmz` have different checksums and byte-identical inner KML.

Unpacked, the file needs no reformatting at all: Organic Maps already writes one `<when>`
and one `<gx:coord>` per line, and the export is append-only. Measured across the 2026-07-27
and 2026-08-14 exports, the diff is `83035 insertions(+), 1 deletion(-)` — the deletion
being `<mwm:lastModified>`, and the insertions one new bookmark in place and the new track
appended at the end.

## The superset check

Because the export is cumulative, a new one must contain every `<when>` the committed copy
has, as many times as it has it, and at least as many `<gx:coord>` and `<Placemark>`
elements. The previous copy is the working-tree file, or the repository's HEAD when that file
is missing, so a deleted file does not pass for a first import. If it does not, something upstream lost data — a phone reset, an app reinstall, a track
deleted by accident — and overwriting would propagate the loss to the only remaining copy.
So the import refuses, names what went missing, and leaves the decision to a human. This is
`backup-documents.sh`'s `MIN_FRACTION` guard in a different costume, and for the same reason:
a real deletion is a decision, a collection that empties itself is an accident.

    python3 -m boattracker.nfl.import_phone_export                    # report
    python3 -m boattracker.nfl.import_phone_export --write --commit   # install and commit

Only after the commit is the `.kmz` safe to delete from the mirror; the tool says so then,
and not before.
"""
import argparse
import glob
import os
import re
import shlex
import shutil
import subprocess
import sys
import zipfile
from collections import Counter

from boattracker import config

## The Syncthing mirror of each phone's Download/ folder; see ORGANICMAPS-SYNC.md for why
## the app's own directory cannot be synced and an export button is the only route. Each
## phone records its own track, so each gets its own file: one phone's export never holds
## the other's positions, and a shared file would fail the superset check on every switch.
PHONES = {'newmi': '~/Downloads/newmi', 'pixel': '~/Downloads/pixel'}

WHEN = re.compile(r'<when>([^<]+)</when>')
MODIFIED = re.compile(r'<mwm:lastModified>([^<]+)</mwm:lastModified>')
## What else an export must not lose: the positions themselves, and the bookmarks and tracks.
COUNTED = (('<gx:coord>', re.compile(r'<gx:coord>')), ('<Placemark>', re.compile(r'<Placemark[\s>]')))


def phone_dir():
    """`<data>/../phone` — beside the boat corpus, not inside it. They are different data."""
    return os.path.join(os.path.dirname(os.path.normpath(config.DATA)), 'phone')


def target_name(phone):
    return '%s.kml' % phone


def newest_export(dirs):
    """The most recently modified .kmz across `dirs`, or None."""
    found = []
    for d in dirs:
        found += glob.glob(os.path.join(os.path.expanduser(d), '*.kmz'))
    return max(found, key=os.path.getmtime) if found else None


def inner_kml(path):
    """The single .kml member's text. A KMZ carrying anything else is refused."""
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if n.lower().endswith('.kml')]
        if len(names) != 1:
            raise ValueError('%s holds %d .kml members, expected exactly one' % (path, len(names)))
        return z.read(names[0]).decode('utf-8')


def when_timestamps(text):
    """Every recorded instant, counted: two fixes may share a second, and losing one counts."""
    return Counter(WHEN.findall(text))


def missing_timestamps(old_text, new_text):
    """Recorded instants the committed copy has and the new export does not."""
    return when_timestamps(old_text) - when_timestamps(new_text)


def shrinkage(old_text, new_text):
    """Why `new_text` is not a superset of `old_text`, one line per reason; [] when it is."""
    why = []
    lost = missing_timestamps(old_text, new_text)
    if lost:
        why.append('%d recorded positions are absent from this export' % sum(lost.values()))
        why += ['  missing: %s' % w for w in sorted(lost)[:5]]
    for name, pattern in COUNTED:
        old, new = len(pattern.findall(old_text)), len(pattern.findall(new_text))
        if new < old:
            why.append('%s count fell from %d to %d' % (name, old, new))
    return why


def last_modified(text):
    m = MODIFIED.search(text)
    return m.group(1) if m else 'unknown'


def git(out, *args, **kw):
    return subprocess.run(['git', '-C', out, *args], capture_output=True, text=True, **kw)


def is_repo_top(out):
    r = git(out, 'rev-parse', '--show-toplevel') if os.path.isdir(out) else None
    return bool(r and r.returncode == 0 and os.path.realpath(r.stdout.strip()) == os.path.realpath(out))


def previous_copy(out, name):
    """The copy to check against, and where it came from: the working tree, else HEAD.

    Falling back to HEAD keeps a file deleted from the working tree from reading as a first
    import, which would skip the one check this module exists for.
    """
    path = os.path.join(out, name)
    if os.path.exists(path):
        with open(path, encoding='utf-8') as f:
            return f.read(), path
    if is_repo_top(out):
        r = git(out, 'show', 'HEAD:%s' % name)
        if r.returncode == 0:
            return r.stdout, 'HEAD:%s' % name
    return None, None


def import_one(phone, src, out, write, commit):
    name = target_name(phone)
    target = os.path.join(out, name)
    try:
        new = inner_kml(src)
    except (zipfile.BadZipFile, ValueError, UnicodeDecodeError) as e:
        print('refusing %s: %s' % (src, e), file=sys.stderr)
        return 1

    fixes = sum(when_timestamps(new).values())
    print('%s: %s\n  exported %s, %d recorded positions, %d lines'
          % (phone, src, last_modified(new), fixes, new.count('\n')))

    added = fixes
    old, where = previous_copy(out, name)
    if old is not None:
        why = shrinkage(old, new)
        if why:
            print('REFUSING: this export has lost data %s holds:' % where, file=sys.stderr)
            for w in why:
                print('  ' + w, file=sys.stderr)
            print('An export should only ever grow. Check the phone before overwriting.',
                  file=sys.stderr)
            return 1
        added = fixes - sum(when_timestamps(old).values())
        print('  superset check passed; %d new positions since %s' % (added, last_modified(old)))
    else:
        print('  first import; no previous copy to check against')

    if not write:
        print('  nothing written (pass --write)')
        return 0
    if commit and not is_repo_top(out):
        print('refusing to write: %s is not the top of a git repository, so --commit cannot'
              ' record it' % out, file=sys.stderr)
        return 1

    os.makedirs(out, exist_ok=True)
    tmp = target + '.new'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(new)
    shutil.move(tmp, target)
    print('  written to %s' % target)

    msg = 'phone: %s export of %s, %d positions (+%d)' % (phone, last_modified(new)[:10], fixes, added)
    if not commit:
        print('  commit it with:  git -C %s add %s && git -C %s commit -m %s'
              % (shlex.quote(out), name, shlex.quote(out), shlex.quote(msg)))
        print('  and only then delete the .kmz from the phone mirror.')
        return 0
    git(out, 'add', name, check=True)
    if git(out, 'diff', '--cached', '--quiet', '--', name).returncode == 0:
        print('  identical to the committed copy; nothing to commit')
    else:
        r = git(out, 'commit', '-m', msg, '--', name)
        if r.returncode != 0:
            print('commit failed; the export is written but not committed:\n%s%s'
                  % (r.stdout, r.stderr), file=sys.stderr)
            return 1
    print('\nThe .kmz in the phone mirror can now be deleted; Syncthing will tidy the phone too.')
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--phone', choices=sorted(PHONES), help='only this phone (default: every phone)')
    ap.add_argument('--src', help='a specific .kmz (needs --phone; default: the newest in its mirror)')
    ap.add_argument('--out', help='target directory (default: <data>/../phone)')
    ap.add_argument('--write', action='store_true', help='install the export')
    ap.add_argument('--commit', action='store_true',
                    help='git-commit the result in the target repository')
    a = ap.parse_args(argv)
    if a.src and not a.phone:
        ap.error('--src needs --phone, to know which file it replaces')
    out = a.out or phone_dir()

    status = 0
    for phone in [a.phone] if a.phone else sorted(PHONES):
        src = a.src or newest_export([PHONES[phone]])
        if not src:
            print('%s: no .kmz in %s' % (phone, PHONES[phone]), file=sys.stderr if a.phone else sys.stdout)
            status = max(status, 1 if a.phone else 0)
            continue
        status = max(status, import_one(phone, src, out, a.write, a.commit))
    return status

if __name__ == '__main__':
    raise SystemExit(main())
