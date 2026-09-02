"""Pull the journey's *rendered* geometry back out of noforeignland into local GPX.

**This is the tool that makes a deletion safe.** The owner's rule of 2026-08-12 — see the
precedence rule in `../SOURCES.md` — is that less reliable data stops being used *on the
site* but is kept locally. So the order for anything coming off the journey is: export here
into `../nfl-retired/`, verify the GPX, and only then delete.

This closes the one hole in the whole workflow. Points added to a line by hand in the web
map exist **nowhere locally** — `SOURCES.md` and `IMPROVE-TRACKS.md` both warn about it, and
the 2025-08 gap-fill chain was uploaded with 5 points, rendered 16, and survived a deletion
only because a snapshot happened to have been taken minutes earlier. Until now the advice was
"take a snapshot"; a snapshot is a 2 MB JSON blob, not something you can re-upload. This turns
it back into the GPX files the importer accepts.

## Where the hand-edits actually live

Not on the `fixes` features. The journey GeoJSON carries **two** features per fix:

* `layer: "fixes"`, a `Point` — the fix itself, one vertex, carrying `timeMs` and `source`
* no `layer`, a `LineString` — the drawn track, carrying only `fixId` and `boatId`

Only the second holds the geometry, and only its vertices carry the hand-placed points. Look
at the `Point` alone — which is what a naive read of the API does — and every fix appears to
be a single position with no track at all.

## The leading connector

**Every rendered LineString begins with the *previous* fix's position.** That first vertex is
an artefact of drawing order, not part of this leg, and re-uploading it would duplicate the
previous leg's endpoint. `--strip-connector` drops it when it coincides with the preceding
fix; the default keeps everything, because for *preservation* a faithful copy is the point.

## Timestamps

Vertices are `[lon, lat, epoch_ms]`. Many 2023 vertices carry epoch 0 — no time at all — and
those are written without a `<time>` element rather than dated to 1970.
"""
import argparse
import json
import os
import urllib.request
from datetime import UTC, datetime

from boattracker import config

__getattr__ = config.lazy_module_getattr(
    'JOURNEY_URL',
    BOAT=lambda: str(config.BOAT_ID),
    API=lambda: config.JOURNEY_URL)
OUT = config.GPXDIR


def journey_request():
    """The read request, carrying a browser User-Agent.

    Without one noforeignland answers **403 Forbidden**, which reads exactly like an
    expired credential and sent the first attempt off hunting for a fresh token. There
    is no token on the read path — the journey is public and the same URL returns 200
    the moment the header is present. `nfl_auth.UA` is the one copy of that string.
    """
    from boattracker.nfl import nfl_auth
    return urllib.request.Request(config.JOURNEY_URL, headers={'User-Agent': nfl_auth.UA})


def fetch(path=None):
    return json.loads(fetch_bytes(path))


def fetch_bytes(path=None):
    """The journey reply exactly as the server (or the file) has it, unparsed."""
    if path:
        with open(path, 'rb') as f:
            return f.read()
    # 2.4 MB, and it normally arrives in ~2 s (measured 2026-08-11). But a session on
    # 2026-08-09 hit `TimeoutError` at 120 s and had to work from a snapshot for the rest of
    # the day, so the server is occasionally very slow rather than the journey being too big
    # to fetch. Waiting the slowness out beats failing in a way that reads like "too large".
    with urllib.request.urlopen(journey_request(), timeout=600) as r:
        return r.read()


def fixes_and_lines(doc):
    """{fixId: {'point': (lat, lon, ms), 'source': str, 'line': [(lat, lon, ms), ...]}}"""
    out = {}
    for f in doc['geojson']['features']:
        p, g = f['properties'], f['geometry']
        fid = p.get('fixId')
        if fid is None:
            continue
        e = out.setdefault(fid, {'point': None, 'source': None, 'line': []})
        if g['type'] == 'Point':
            c = g['coordinates']
            e['point'] = (c[1], c[0], p.get('timeMs'))
            e['source'] = p.get('source')
        else:
            e['line'] = [(v[1], v[0], v[2] if len(v) > 2 else 0) for v in g['coordinates']]
    return out


def in_range(entries, lo, hi):
    out = {}
    for fid, e in entries.items():
        ms = (e['point'] or (None, None, None))[2]
        if not ms:
            continue
        day = datetime.fromtimestamp(ms / 1000, UTC).strftime('%Y-%m-%d')
        if (not lo or day >= lo) and (not hi or day <= hi):
            out[fid] = e
    return out


def strip_connector(line, prev_point, tol_deg=1e-6):
    """Drop the leading vertex when it is the previous fix's position."""
    if not line or prev_point is None:
        return line, False
    la, lo, _ = line[0]
    pla, plo = prev_point[0], prev_point[1]
    if abs(la - pla) < tol_deg and abs(lo - plo) < tol_deg:
        return line[1:], True
    return line, False


def gpx(name, line, creator):
    head = ('<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<gpx version="1.1" creator="{creator}"\n'
            '     xmlns="http://www.topografix.com/GPX/1/1">\n'
            ' <metadata>\n'
            f'  <name>{name}</name>\n')
    times = [ms for _, _, ms in line if ms]
    if times:
        head += ('  <time>' + datetime.fromtimestamp(max(times) / 1000, UTC)
                 .strftime('%Y-%m-%dT%H:%M:%SZ') + '</time>\n')
    body = [head, ' </metadata>\n', ' <trk>\n', f'  <name>{name}</name>\n', '  <trkseg>\n']
    for la, lo, ms in line:
        t = ('<time>' + datetime.fromtimestamp(ms / 1000, UTC)
             .strftime('%Y-%m-%dT%H:%M:%SZ') + '</time>') if ms else ''
        body.append(f'   <trkpt lat="{la}" lon="{lo}">{t}</trkpt>\n')
    body += ['  </trkseg>\n', ' </trk>\n', '</gpx>\n']
    return ''.join(body)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--from', dest='lo', help='first day (YYYY-MM-DD)')
    ap.add_argument('--to', dest='hi', help='last day')
    ap.add_argument('--snapshot', help='read a saved snapshot instead of the live API')
    ap.add_argument('--out', default=OUT)
    ap.add_argument('--prefix', default='nfl-rendered')
    ap.add_argument('--strip-connector', action='store_true',
                    help="drop each line's leading vertex when it repeats the previous fix")
    ap.add_argument('--write', action='store_true', help='write the GPX files')
    a = ap.parse_args()

    entries = fixes_and_lines(fetch(a.snapshot))
    sel = in_range(entries, a.lo, a.hi)
    order = sorted(sel, key=lambda f: sel[f]['point'][2])
    print(f'{len(sel)} fixes in range\n')
    print(f'{"fix time (UTC)":18s} {"fixId":18s} {"src":12s} {"vertices":>8s}  {"conn":>4s}')
    total_v = 0
    prev_point = None
    for fid in order:
        e = sel[fid]
        line = e['line']
        stripped = False
        if a.strip_connector:
            line, stripped = strip_connector(line, prev_point)
        dt = datetime.fromtimestamp(e['point'][2] / 1000, UTC)
        total_v += len(line)
        name = f'{dt:%Y-%m-%d %H:%M} rendered journey line (fix {fid})'
        print(f'{dt:%Y-%m-%d %H:%M}   {fid}  {str(e["source"])[:12]:12s} {len(line):8d}'
              f'  {"yes" if stripped else "-":>4s}')
        if a.write and line:
            os.makedirs(a.out, exist_ok=True)
            fn = f'{a.prefix}-{dt:%Y-%m-%d-%H%M}-{fid}.gpx'
            with open(os.path.join(a.out, fn), 'w') as f:
                f.write(gpx(name, line,
                            'rendered noforeignland journey line, recovered from the site - '
                            'includes points hand-placed on the map that exist nowhere else'))
        prev_point = e['point']
    print(f'\n{total_v} vertices across {len(sel)} fixes')
    if a.write:
        print(f'written to {a.out}/{a.prefix}-*.gpx')
    else:
        print('(dry run - pass --write to save)')


if __name__ == '__main__':
    main()
