"""Write a fix's line back to noforeignland over the API, instead of by email.

The call the web map itself makes when the owner drags points on a track, captured from the
browser on 2026-08-05:

    PUT https://www.noforeignland.com/api/v1/boat/fix/path
    authorization: <the same token nfl_auth.py handles>
    content-type: multipart/form-data

    fixId = 6755398652989521
    path  = [{"lat":58.308267,"lon":11.367783}, ...]

## Why this matters

Every geometry change until now went by **email**, one GPX per message, and the site owner
pays his provider per volume for inbound mail. This project alone sent 106 tracker legs plus
the 2021 return. This endpoint removes that cost for any change to an *existing* fix's line,
and removes the delete-and-re-upload dance with it: correcting a route is now one call that
keeps the fix, its id and its timestamp.

Import by email is still the only way to create a *new* fix from a GPX **in one step**. The
two-step route needs no mail at all, and is how a track is built under the current rules:

    python3 add_fixes.py --plan plan.json          # 1. the fix: position + arrival instant
    python3 put_fix_path.py --fix-id <id> --path p.json   # 2. the geometry hung on it

Remember what the fix is: **one timestamp for the whole line**, and that timestamp is the
leg's *arrival*. One fix, one leg, from one significant stop to the next — see
`../IMPROVE-TRACKS.md`. (An "about two hours" target was withdrawn on 2026-08-12: it
assumed a fix carries one timestamp, and vertices carry their own.) A fix
left without geometry is a bare point, which is correct at a harbour or anchorage between
two tracks and wrong in the middle of one.

## The danger, and why this module is mostly refusals

**It replaces the whole path.** Not append, not patch. Send two points and a
seventy-vertex leg becomes a straight line, with no error and no undo — and the owner's
hand-placed points exist nowhere but the site. So:

* `--backup` (on by default) fetches the current path and writes it to a file *before*
  overwriting, which is the only reason this is a reversible operation;
* paths of fewer than two points, coordinates off the planet, and 0,0 are refused outright,
  because each is what a parsing failure looks like rather than a position a boat occupied.

Verify afterwards with `reimport_journey.py`, as always: HTTP 200 is not evidence.
"""
import argparse
import json
import os
import subprocess
import sys
import time

from boattracker import config, files
from boattracker.nfl import nfl_auth

URL = f'{config.FIX_URL}/path'
BACKUP_DIR = config.GPXDIR


def path_field(points):
    """The `path` form field: a JSON array of {lat, lon}, at full precision.

    Key order and spacing follow the captured request. Precision is left alone - the map
    sends fifteen significant digits and rounding here would move points silently.

    Exact consecutive repeats are dropped first. The *rendered* line reports its first
    vertex twice - the leading connector, an artefact of drawing order - while the stored
    path holds it once, so a rendered path fed back here unchanged would grow one duplicate
    per round trip. A zero-length segment carries nothing either way.
    """
    pts = []
    for p in points:
        if not pts or tuple(p) != tuple(pts[-1]):
            pts.append(tuple(p))
    if len(pts) < 2:
        raise ValueError(f'a path needs at least two points, got {len(pts)} - '
                         'sending this would erase the leg')
    out = []
    for lat, lon in pts:
        if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
            raise ValueError(f'{lat},{lon} is out of range for a position')
        if lat == 0 and lon == 0:
            raise ValueError('0,0 is what a failed parse looks like, not a position')
        out.append({'lat': lat, 'lon': lon})
    return json.dumps(out, separators=(',', ':'))


def curl_command(fix_id, points, token):
    """The argv for the PUT. The token goes in a header, never in the URL."""
    return [
        'curl', '-s', '-m', '60', '-o', '/dev/null', '-w', '%{http_code}',
        '-X', 'PUT', URL,
        '-H', 'accept: application/json, text/plain, */*',
        '-H', f'authorization: {token}',
        '-H', 'origin: https://www.noforeignland.com',
        '-H', f'referer: {config.REFERER}',
        '-H', 'sec-fetch-dest: empty', '-H', 'sec-fetch-mode: cors',
        '-H', 'sec-fetch-site: same-origin', '-A', nfl_auth.UA,
        '-F', f'fixId={fix_id}',
        '-F', f'path={path_field(points)}',
    ]


def current_path(fix_id):
    """The fix's line as the site holds it now, via `reimport_journey`."""
    from boattracker.nfl import reimport_journey
    entry = reimport_journey.fixes_and_lines(reimport_journey.fetch()).get(int(fix_id))
    if entry is None:
        return None
    return [(la, lo) for la, lo, _ in entry['line']]


def back_up(fix_id, points, directory=BACKUP_DIR):
    """Write the pre-change path where it can be put back. Returns the file path."""
    os.makedirs(directory, exist_ok=True)
    dest = os.path.join(directory, f'fixpath-before-{fix_id}-{time.strftime("%Y%m%dT%H%M%S")}.json')
    with open(dest, 'w') as f:
        json.dump([{'lat': la, 'lon': lo} for la, lo in points], f, indent=1)
    return dest


def put(fix_id, points, token, timeout=60):
    r = subprocess.run(curl_command(fix_id, points, token), capture_output=True, text=True)
    return r.stdout.strip()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--fix-id', required=True)
    ap.add_argument('--path', required=True,
                    help='JSON file: [[lat, lon], ...] or [{"lat":..,"lon":..}, ...]')
    ap.add_argument('--token-file', default=None)
    ap.add_argument('--no-backup', action='store_true',
                    help='skip saving the current path first (do not)')
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()

    raw = files.read_json(a.path)
    pts = [(p['lat'], p['lon']) if isinstance(p, dict) else (p[0], p[1]) for p in raw]
    field = path_field(pts)          # validates before anything is fetched or sent

    print(f'fix {a.fix_id}: {len(pts)} points, {len(field)} bytes')
    print(f'  first {pts[0][0]:.6f},{pts[0][1]:.6f}   last {pts[-1][0]:.6f},{pts[-1][1]:.6f}')

    if not a.no_backup:
        before = current_path(a.fix_id)
        if before is None:
            sys.exit(f'fix {a.fix_id} is not on the journey — refusing to write a path to it')
        print(f'  currently {len(before)} points on the site')
        if not a.dry_run:
            print(f'  backed up to {back_up(a.fix_id, before)}')

    if a.dry_run:
        print('dry run — nothing sent')
        return

    token = files.read_stripped(a.token_file) if a.token_file else nfl_auth.load()
    code = put(a.fix_id, pts, token)
    print(f'HTTP {code}')
    if code != '200':
        sys.exit('not accepted')
    print('verify with reimport_journey.py — HTTP 200 is not evidence')


if __name__ == '__main__':
    main()
