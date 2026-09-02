"""Fetch the noforeignland journey and write it as line-oriented JSON, for git.

Until now the snapshot was a `curl` line in `IMPROVE-TRACKS.md` §1 writing a 2.4 MB blob
into `nfl-snapshots/`, one file per write-session, none of them version controlled. Those
still have their job — a copy taken seconds before a deletion, because the API has no undo
— and `--raw` writes the reply's bytes exactly as `curl` did, but refuses to overwrite an
earlier copy.

What this module adds is a **single tracked snapshot** that can live in the journey record
and be committed after every change, so `git log -p` answers "when did this fix disappear,
and what else moved when it did".

## Why the file has to be reformatted first

The API answers on one line. Git will still store that efficiently — packfile deltas are
binary, and 67 real snapshots (149 MB) pack to 1.6 MB untouched — so this is not about
disk. It is about the diff. The 2026-08-11 window-dedupe, which deleted four fixes, reads
as `1 insertion(+), 1 deletion(-)` in the API's own format and as 7 insertions and 56
deletions here, naming every fix that went and every chapter mileage that moved with it.

## What may and may not be changed on the way through

The server's output is already deterministic and meaningfully ordered — two consecutive
fetches on 2026-09-02 were byte-identical, and features arrive as the `fixes` Points sorted
by `timeMs` followed by the LineStrings in the same fix order. So this **does not sort
anything**: re-ordering would be a large invented diff the first time and a risk of
churn thereafter. It only inserts line breaks, sorts *keys* within an object, and writes
integral floats as integers wherever they occur, because `1.6209162E12` and `1620916200000.0` are the same
number wearing two hats and only one of them is readable.

`dumps()` is checked against the input on every write: the file it produces must parse back
to an equal object, or nothing is written. That check is what makes the reformatting safe
to do to the only copy of a hand-placed map correction. A key the layout does not know is
written verbatim and reported on stderr, since it means the API has changed.

## Two counters drift on their own

`days` at the top level, and the open chapter's `days`, are derived from the wall clock:
1927 on 2026-08-11 and 1949 on 2026-09-02 with no data change behind it. So a commit will
often carry those two lines and nothing else. That is not evidence of an edit, and
`--if-changed` refuses to write when they are the only difference.
"""
import argparse
import json
import os
import sys

from boattracker import config
from boattracker.nfl.reimport_journey import fetch_bytes

## The counters that move with the calendar rather than with the journey.
DRIFTING = ('days',)

## The keys the one-vertex-per-line layout knows. Anything else is kept, written verbatim,
## and reported by `unknown_keys()` — a new key means the API changed, and someone should know.
FEATURE_KEYS = ('type', 'properties', 'geometry')
GEOMETRY_KEYS = ('type', 'coordinates')
GEOMETRY_TYPES = ('Point', 'LineString')


def _ints(x):
    """`1.6209162E12` and `1620916200000.0` both become `1620916200000`, anywhere in `x`.

    Bounded by 2**53 because beyond that a float has already lost the integer it claims to
    be, and silently writing the wrong number is worse than writing an ugly one.
    """
    if isinstance(x, float) and x.is_integer() and abs(x) < 2 ** 53:
        return int(x)
    if isinstance(x, list):
        return [_ints(v) for v in x]
    if isinstance(x, dict):
        return {k: _ints(v) for k, v in x.items()}
    return x


def _j(x):
    ## NaN and Infinity are not JSON; refusing them beats writing a file other tools cannot read.
    return json.dumps(x, sort_keys=True, allow_nan=False)


def _laid_out(f):
    """True for a feature in the shape the line-per-vertex layout is written for."""
    return (isinstance(f, dict) and set(FEATURE_KEYS) <= f.keys()
            and isinstance(f['geometry'], dict) and set(GEOMETRY_KEYS) <= f['geometry'].keys())


def unknown_keys(doc):
    """What in `doc`'s features the layout does not know, one description per kind."""
    found = set()
    for f in doc.get('geojson', {}).get('features', []):
        if not _laid_out(f):
            found.add('a feature shaped %s' % _j(f)[:80])
            continue
        g = f['geometry']
        found.update('feature key %r' % k for k in f if k not in FEATURE_KEYS)
        found.update('geometry key %r' % k for k in g if k not in GEOMETRY_KEYS)
        if g['type'] not in GEOMETRY_TYPES:
            found.add('geometry type %r' % g['type'])
    return sorted(found)


def dump(doc, out):
    """Write `doc` to the file object `out`, one vertex per line."""
    out.write(dumps(doc))


def _feature(f, ftail):
    """One feature: a line each for type and properties, and one per vertex of the geometry."""
    if not _laid_out(f):
        return ['   %s%s\n' % (_j(f), ftail)]
    geom = f['geometry']
    extra = sorted(k for k in f if k not in FEATURE_KEYS)
    gclose = ''.join(', %s: %s' % (_j(k), _j(geom[k])) for k in sorted(geom) if k not in GEOMETRY_KEYS) + '}'
    end = ',' if extra else '}' + ftail
    w = ['   {"type": %s,\n' % _j(f['type']),
         '    "properties": %s,\n' % _j(f['properties'])]
    cs = geom['coordinates']
    if geom['type'] == 'Point' or not isinstance(cs, list):
        w.append('    "geometry": {"type": %s, "coordinates": %s%s%s\n' % (_j(geom['type']), _j(cs), gclose, end))
    else:
        w.append('    "geometry": {"type": %s, "coordinates": [\n' % _j(geom['type']))
        for ci, c in enumerate(cs):
            w.append('     %s%s\n' % (_j(c), ',' if ci < len(cs) - 1 else ''))
        w.append('    ]%s%s\n' % (gclose, end))
    for ei, k in enumerate(extra):
        w.append('    %s: %s%s\n' % (_j(k), _j(f[k]), ',' if ei < len(extra) - 1 else '}' + ftail))
    return w


def dumps(doc):
    """The journey as line-oriented JSON. Parses back to an object equal to `doc`."""
    doc = _ints(doc)
    w = []
    keys = sorted(doc)
    w.append('{\n')
    for ki, k in enumerate(keys):
        tail = ',' if ki < len(keys) - 1 else ''
        if k != 'geojson':
            body = json.dumps(doc[k], sort_keys=True, indent=1, allow_nan=False).replace('\n', '\n ')
            w.append(' %s: %s%s\n' % (json.dumps(k), body, tail))
            continue
        g = doc[k]
        w.append(' "geojson": {\n')
        gkeys = sorted(g)
        for gi, gk in enumerate(gkeys):
            gtail = ',' if gi < len(gkeys) - 1 else ''
            if gk != 'features':
                w.append('  %s: %s%s\n' % (json.dumps(gk), _j(g[gk]), gtail))
                continue
            w.append('  "features": [\n')
            feats = g['features']
            for fi, f in enumerate(feats):
                w += _feature(f, ',' if fi < len(feats) - 1 else '')
            w.append('  ]%s\n' % gtail)
        w.append(' }%s\n' % tail)
    w.append('}\n')
    return ''.join(w)


def only_drift(old_text, new_doc):
    """True when the only difference from the committed file is the calendar counters.

    Compares the parsed documents rather than the text, so a reformatting of the old file
    does not read as a change; `DRIFTING` and every chapter's `days` are blanked on both
    sides before the comparison.
    """
    try:
        old = json.loads(old_text)
    except ValueError:
        return False

    def flatten(d):
        d = json.loads(json.dumps(d))
        for k in DRIFTING:
            d.pop(k, None)
        for ch in d.get('chapters', []):
            ch.pop('days', None)
        return d

    return flatten(old) == flatten(new_doc)


def default_out():
    return os.path.join(config.JOURNEY, 'journey-snapshot.json')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--out', help='where to write (default: <journey>/journey-snapshot.json)')
    ap.add_argument('--from-file', dest='src', help='reformat this file instead of fetching')
    ap.add_argument('--raw', action='store_true',
                    help='write the API reply byte for byte, as the nfl-snapshots/ copies are; never overwrites')
    ap.add_argument('--if-changed', action='store_true',
                    help='write nothing when only the calendar-derived counters moved')
    args = ap.parse_args(argv)

    out = args.out or default_out()
    reply = fetch_bytes(args.src)

    if args.raw:
        ## `x`: a second write-session on the same day must not replace the morning's copy,
        ## which may be the only record of what that session deleted.
        try:
            with open(out, 'xb') as f:
                f.write(reply)
        except FileExistsError:
            print('refusing to write: %s already exists, and may be the only record of an earlier'
                  ' session' % out, file=sys.stderr)
            return 1
        print('%s: %d bytes, raw' % (out, len(reply)))
        return 0

    doc = json.loads(reply)
    for u in unknown_keys(doc):
        print('WARNING: the journey carries %s, which the layout does not know. It is kept, written'
              ' verbatim, but the API may have changed.' % u, file=sys.stderr)

    ## The only copy of a hand-placed map correction may pass through here, so the
    ## reformatting is verified before it is allowed to land, not after.
    try:
        text = dumps(doc)
        same = json.loads(text) == doc
    except (TypeError, KeyError, AttributeError, ValueError) as e:
        print('refusing to write: the snapshot could not be reformatted (%r)' % e, file=sys.stderr)
        return 1
    if not same:
        print('refusing to write: the reformatted snapshot does not match the source', file=sys.stderr)
        return 1

    if args.if_changed and os.path.exists(out):
        with open(out) as f:
            if only_drift(f.read(), doc):
                print('%s: unchanged apart from the calendar counters, not written' % out)
                return 0

    tmp = out + '.new'
    with open(tmp, 'w') as f:
        f.write(text)
    os.replace(tmp, out)
    print('%s: %d features, %d lines, %s miles'
          % (out, len(doc['geojson']['features']), text.count('\n'), doc.get('miles')))
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
