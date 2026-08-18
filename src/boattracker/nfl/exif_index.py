"""Build and query an index of photograph timestamps and GPS positions.

A geotagged photograph is exact to the second, which makes it second only to the engine log as
dating evidence — and unlike the engine log it also gives a position. `SOURCES.md` calls it the
cheapest untapped source in the project, and it has stayed untapped because the sweep was only
ever run over a handful of days at a time.

This indexes the whole corpus once, incrementally, so that every later question is a cheap
lookup instead of another sweep. Two reasons to scan everything rather than filter by filename
first: a file whose name carries no date, or a misleading one, still has EXIF, and the earlier
approach of matching filenames against the dates under investigation would silently skip exactly
those. There are 308 undated filenames in the corpus.

## What is stored

One record per file with usable metadata, in `<photos>/exif-index.json`, `[paths] photos` in the config:

    {"path": "pixel/IMG_20210704_120133.jpg",   # relative to the photo root
     "time": "2021-07-04T12:01:33",             # DateTimeOriginal, or CreateDate as fallback
     "lat": 43.18986, "lon": 27.921049,         # null when the file carries no GPS
     "model": "Pixel 4a",
     "fix": "GPS",                              # GPSProcessingMethod: GPS, CELLID, NETWORK, ...
     "gps_time": "2021:07:04 10:01:31Z",        # GPSDateTime, the fix's own clock
     "hpe": 12.0}                               # GPSHPositioningError in metres, when written

## `fix` is a precision class, not a verdict

It says how the position was obtained, which bounds its *precision*: `CELLID` is cell-tower
trilateration, typically 1-10 km — enough to say which harbour, useless as track geometry —
while `GPS` is normally metres.

It does **not** say whether the position is right, and must not be used as a reliability
flag. Two cases from 2022, in opposite directions:

* `huawei/IMG_20220723_215745.jpg` is labelled **GPS** and is wrong by **900 nm**. The
  picture shows a Kiel canal lock; the position is the Gdansk basin, where the phone last
  had a real lock before going to sea. A cached position written with a fresh timestamp.
* The same day's `IMG_20220723_135026.jpg` is labelled **CELLID** and is *correct* —
  mid-canal, consistent with the diary.

So a gross error can wear the good label and a good position the bad one. Reliability has
to be derived: `fix` for the precision bound, `photo_survey.py`'s 0.4-9.0 kn check for
impossible movement, and agreement with the day's other photographs.

`gps_time` is worth keeping for a different reason: when the fix's own date differs from the
photograph's date, the position is stale outright. That test would not have caught the case
above — its GPS clock was contemporaneous — but it catches the ordinary kind.

Files with a timestamp but no GPS are kept deliberately, and are as important as the geotagged
ones here. The owner can often supply the location from memory, so a photograph with a time and
no position is not a dead end — it is a question waiting to be answered. `--missing` groups them
**by day**, with the geotagged positions of that same day alongside, because the practical unit
of recall is "where was the boat that day" rather than "where was this photograph".

## The owner's recall, kept separate

`--locations FILE` merges `<photos>/manual-locations.json` over the index at report
time. Entries are keyed by `day` or by `path`, and a `path` entry wins — prefer it. A day-level
flag on 2021-05-17 would have discarded that afternoon's passage south, because only the two
morning photographs were ashore.

The merge is deliberately *not* written back into the index. The index stays a faithful record of
what the cameras wrote, and the recall stays separately auditable — so a remembered position can
never be mistaken later for something EXIF actually said.

Three distinct cases, and using the wrong one corrupts the record:

* **`ashore: true`** — the position is *true* but is not the boat: the photographer was ashore,
  on a train, or a thousand miles away. Two days of 2021 sit at Tromsø. The photograph keeps its
  own position; the flag only says it must not become boat track. An entry may still carry
  `lat`/`lon` as context for where the *boat* was, and those coordinates are not applied.
* **`override: true`** with `lat`/`lon` — the EXIF position is **false** and is replaced. The
  original is preserved as `exif_lat`/`exif_lon` so the correction stays auditable.
* **`drop: true`** — the EXIF position is false and no replacement is known.

Supplying `lat`/`lon` *without* `override` fills a missing position only; it will never displace
a measured one. That asymmetry is the point: recall must not quietly overwrite measurement. It is
also why `override` is an explicit key rather than being inferred from the presence of
coordinates — 2021-05-16 has both a real Göteborg position and the boat's Strömstad position in
the same entry, and inferring would have moved the photographs to the wrong place.

## Incremental

The index is keyed by path and merged on each run, so re-running costs only the new files. Pass
`--rescan` to re-read paths already present.

## Timezone

EXIF `DateTimeOriginal` has no timezone: it is whatever the camera's clock said, which for a
phone is normally local time at the place the photo was taken. Times are stored exactly as read,
**without** conversion, because guessing the offset would corrupt the one thing photographs are
good for. Any consumer comparing them with UTC track data has to apply the offset for the
region and season itself — three hours for Bulgaria and Turkey in summer, two for most of the
2021 Mediterranean.
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime

from boattracker import config

__getattr__ = config.lazy_module_getattr(
    'PHOTOS',
    ROOT=lambda: config.PHOTOS,
    INDEX=lambda: f'{config.PHOTOS}/exif-index.json',
    MANUAL=lambda: f'{config.PHOTOS}/manual-locations.json')

## argparse builds every argument before it can print --help, so a `const=WANT_DEFAULT_LOCATIONS` there
## would demand a configured photo archive just to read the usage text.
WANT_DEFAULT_LOCATIONS = ''
EXTS = ('.jpg', '.jpeg', '.png', '.heic', '.heif', '.dng', '.tif', '.tiff',
        '.mp4', '.mov', '.3gp', '.avi', '.webp')

def load():
    if os.path.exists(f'{config.PHOTOS}/exif-index.json'):
        with open(f'{config.PHOTOS}/exif-index.json') as f:
            return {r['path']: r for r in json.load(f)}
    return {}

def candidates():
    out = []
    for dirpath, _dirs, files in os.walk(config.PHOTOS):
        for fn in files:
            if fn.lower().endswith(EXTS):
                out.append(os.path.relpath(os.path.join(dirpath, fn), config.PHOTOS))
    return sorted(out)

def read_batch(paths, chunk=400):
    """exiftool in batch mode; one process per chunk keeps the argument list sane."""
    got = []
    for i in range(0, len(paths), chunk):
        part = paths[i:i+chunk]
        cmd = ['exiftool', '-j', '-n', '-fast2', '-q', '-q',
               '-DateTimeOriginal', '-CreateDate', '-GPSLatitude', '-GPSLongitude',
               '-Model', '-GPSDateTime', '-GPSProcessingMethod',
               '-GPSHPositioningError'] + part
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=config.PHOTOS)
        if not r.stdout.strip():
            continue
        try:
            got.extend(json.loads(r.stdout))
        except json.JSONDecodeError:
            print(f'   (unparseable exiftool output for chunk at {i})', file=sys.stderr)
        print(f'   {min(i+chunk, len(paths))}/{len(paths)}', flush=True)
    return got

def norm_time(rec):
    for key in ('DateTimeOriginal', 'CreateDate'):
        v = rec.get(key)
        if not v or str(v).startswith('0000'):
            continue
        s = str(v).strip()
        # EXIF writes "2021:07:04 12:01:33", sometimes with a subsecond or offset tail
        s = s.split('+')[0].split('-0')[0].split('.')[0].strip()
        try:
            return datetime.strptime(s, '%Y:%m:%d %H:%M:%S').isoformat()
        except ValueError:
            continue
    return None

def apply_manual(have, path):
    """Overlay remembered positions. Never written back to the index - see the docstring."""
    if not os.path.exists(path):
        print(f'no manual locations at {path} (nothing to merge)')
        return have
    with open(path) as f:
        entries = json.load(f)
    by_path = {e['path']: e for e in entries if e.get('path')}
    by_day = {e['day']: e for e in entries if e.get('day')}
    n_fill = n_corr = n_drop = 0
    out = {}
    for k, r in have.items():
        r = dict(r)
        # A path entry is more specific than a day entry and wins.
        e = by_path.get(r['path']) or (by_day.get(r['time'][:10]) if r.get('time') else None)
        if e is not None:
            if e.get('drop'):
                # The camera's position is false and no replacement is claimed.
                if r['lat'] is not None:
                    r['exif_lat'], r['exif_lon'] = r['lat'], r['lon']
                r['lat'] = r['lon'] = None
                r['position_from'] = 'dropped'
                n_drop += 1
            elif e.get('lat') is not None:
                if r['lat'] is None:
                    r['lat'], r['lon'] = e['lat'], e['lon']
                    r['position_from'] = 'recalled'
                    n_fill += 1
                elif e.get('override'):
                    # Recall displaces measurement only when asked for explicitly, and the
                    # measurement stays in the record so the correction can be audited.
                    r['exif_lat'], r['exif_lon'] = r['lat'], r['lon']
                    r['lat'], r['lon'] = e['lat'], e['lon']
                    r['position_from'] = 'corrected'
                    n_corr += 1
            # `ashore` and `note` do not depend on the entry carrying coordinates: most
            # entries are "the photographer was here, the boat was not", with no position
            # to offer. Requiring lat here made those flags inert.
            if 'ashore' in e:
                r['ashore'] = e['ashore']
            if e.get('note'):
                r['note'] = e['note']
        out[k] = r
    ashore = sum(1 for r in out.values() if r.get('ashore'))
    print(f'merged {len(entries)} manual entries: {n_fill} filled in, {n_corr} corrected, '
          f'{n_drop} dropped; {ashore} records marked ashore (not boat positions)')
    return out

def report_missing(rows, a):
    """Per-day: how many photos lack GPS, and what the geotagged ones that day say.

    Grouped by day because that is the unit the owner can answer in. Where a day has some
    geotagged photos, those positions are shown: often they are enough to place the rest of
    that day without any recall at all.
    """
    from collections import defaultdict
    days = defaultdict(lambda: {'no_gps': [], 'gps': []})
    for r in rows:
        days[r['time'][:10]]['gps' if r['lat'] is not None else 'no_gps'].append(r)
    print(f'\n{len(days)} days with photographs\n')
    print(f'{"day":12s} {"no GPS":>7s} {"GPS":>4s}  geotagged positions that day / directories')
    tot_missing = 0
    for day in sorted(days):
        e = days[day]
        tot_missing += len(e['no_gps'])
        if not e['no_gps'] and not a.limit:
            continue
        if e['gps']:
            la = sum(r['lat'] for r in e['gps'])/len(e['gps'])
            lo = sum(r['lon'] for r in e['gps'])/len(e['gps'])
            span = max(((r['lat']-la)**2+(r['lon']-lo)**2)**0.5 for r in e['gps'])
            note = f'{la:9.5f},{lo:9.5f}' + (f' (spread {span*60:.1f}\')' if span > 0.002 else '')
        else:
            dirs = sorted({os.path.dirname(r['path']) or '.' for r in e['no_gps']})
            note = 'none - ' + ', '.join(dirs[:3])
        print(f'{day:12s} {len(e["no_gps"]):7d} {len(e["gps"]):4d}  {note}')
    print(f'\n{tot_missing} photographs without GPS across {len(days)} days')
    nog = [d for d in days if not days[d]['gps'] and days[d]['no_gps']]
    print(f'{len(nog)} of those days have no geotagged photograph at all, so they need recall:')
    print('   ' + ', '.join(sorted(nog)[:24]) + (' ...' if len(nog) > 24 else ''))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--build', action='store_true', help='scan for new files and index them')
    ap.add_argument('--rescan', action='store_true', help='re-read paths already indexed')
    ap.add_argument('--from', dest='lo', help='report records from this date (YYYY-MM-DD)')
    ap.add_argument('--to', dest='hi', help='report records up to this date')
    ap.add_argument('--with-gps', action='store_true', help='only records carrying a position')
    ap.add_argument('--locations', nargs='?', const=WANT_DEFAULT_LOCATIONS,
                    help='merge remembered positions over the index (default: %(default)s)',
                    default=None)
    ap.add_argument('--missing', action='store_true',
                    help='per-day summary of photos lacking GPS, for filling in by hand')
    ap.add_argument('--limit', type=int, default=40)
    a = ap.parse_args()
    if a.locations == WANT_DEFAULT_LOCATIONS:
        a.locations = f'{config.PHOTOS}/manual-locations.json'
    have = load()
    if a.locations:
        have = apply_manual(have, a.locations)
    if a.build:
        cand = candidates()
        todo = cand if a.rescan else [p for p in cand if p not in have]
        print(f'{len(cand)} media files, {len(have)} already indexed, {len(todo)} to read')
        if todo:
            for rec in read_batch(todo):
                path = rec.get('SourceFile')
                if not path:
                    continue
                t = norm_time(rec)
                lat, lon = rec.get('GPSLatitude'), rec.get('GPSLongitude')
                # Exactly 0,0 is null island: the camera wrote a placeholder, not a fix in
                # the Gulf of Guinea. 62 records carried it, and as a position it is worse
                # than none — 6 700 km from anywhere the boat has ever been.
                if lat is not None and lon is not None and float(lat) == 0.0 and float(lon) == 0.0:
                    lat = lon = None
                if t is None and lat is None:
                    continue
                hpe = rec.get('GPSHPositioningError')
                have[path] = {'path': path, 'time': t,
                                  'lat': float(lat) if lat is not None else None,
                                  'lon': float(lon) if lon is not None else None,
                                  'model': rec.get('Model'),
                                  'fix': rec.get('GPSProcessingMethod'),
                                  'gps_time': rec.get('GPSDateTime'),
                                  'hpe': float(hpe) if hpe is not None else None}
            with open(f'{config.PHOTOS}/exif-index.json', 'w') as f:
                json.dump(sorted(have.values(),
                                 key=lambda r: (r['time'] or '', r['path'])), f, indent=1)
            print(f'wrote {len(have)} records to {f'{config.PHOTOS}/exif-index.json'}')
    rows = [r for r in have.values() if r['time']]
    if a.lo:
        rows = [r for r in rows if r['time'][:10] >= a.lo]
    if a.hi:
        rows = [r for r in rows if r['time'][:10] <= a.hi]
    if a.with_gps:
        rows = [r for r in rows if r['lat'] is not None]
    rows.sort(key=lambda r: r['time'])
    if a.missing:
        return report_missing(rows, a)
    gps = sum(1 for r in rows if r['lat'] is not None)
    print(f'\n{len(rows)} records in range, {gps} with GPS')
    for r in rows[:a.limit]:
        pos = (f"{r['lat']:9.5f},{r['lon']:9.5f}" if r['lat'] is not None
               else '        -,        -')
        print(f"   {r['time']}  {pos}  {r['path']}")
    if len(rows) > a.limit:
        print(f'   ... {len(rows)-a.limit} more')

if __name__ == '__main__':
    main()
