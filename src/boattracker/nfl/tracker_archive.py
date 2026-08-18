"""Read the 2021 raw tracker feed out of `gpstracker-archive/` and make days of it.

The single largest recoverable item in the project: the GSM/GPS tracker's raw server log for
**2021-06-15 .. 08-22**, recovered from `/var/www/html/archive/gpstracker.raw.*.bz2` on the
host serving `solveig.oslo.no`. It lands on the 64-day hole the journey currently crosses with
one 122 nm straight line. See `../TRACKS-2021.md`.

## What the archive is, and what has to be done to it

Rotated copies of one append-only log, so **the files overlap** — `foo`, `bar` and the two
`2021-06-2x` files are hand-made copies of stretches also held in the epoch-named ones.
Deduplication is not optional: parsed naively the same fix arrives several times, and the
per-day counts come out inflated.

The wire format is TK103 (`../gt02a.py` parses it, despite the file being named for a GT02A).
Timestamps are **UTC** and arrive slightly out of order — the receiving daemon wrote points
asynchronously — so everything is sorted by time after parsing rather than trusted as read.

## Days, and why they are local

Fixes are UTC; the diary is local, and Norway and Sweden in summer are **UTC+2**. Splitting on
the UTC day would cut an evening arrival after 22:00 local into the following diary day, so the
split is on local days by default (`--tz-offset`). The `<time>` written into the GPX stays UTC.

## What this tool does not do

It does not decide the boat was there. The tracker lived aboard but was not always the point of
interest, and roughly a fifth of the 2021 photograph positions are not the boat at all — the
same `ashore` judgement applies here and is the owner's to make. This tool prints days and
writes GPX; deciding which days become journey legs is a separate step.
"""
import argparse
import bz2
import os
from collections import Counter
from datetime import datetime, timedelta

from boattracker import config  # noqa: E402
from boattracker.tracker.gt02a import BlobError, parse_blob  # noqa: E402
from boattracker.tracker.point import Path, Point, ts2dt  # noqa: E402

ARCHIVE = config.ARCHIVE
GPXDIR = config.GPXDIR
## Shown on the journey as the track's source, so it says what the data *is* rather than
## which host it came off.
CREATOR = 'GSM/GPS tracker aboard, raw server feed recovered from the server archive'
__getattr__ = config.lazy_module_getattr('FROM')
TO = config.TO


def blobs(data):
    """The `(...)`-delimited blobs in a raw log, junk between them dropped."""
    out = []
    for chunk in data.split(b'(')[1:]:
        end = chunk.find(b')')
        if end > 0:
            out.append(chunk[:end])
    return out


def read_file(path):
    """(points, error counter) for one archive file, compressed or not."""
    opener = bz2.open if path.endswith('.bz2') else open
    with opener(path, 'rb') as f:
        data = f.read()
    points, errors = [], Counter()
    for blob in blobs(data):
        try:
            point = parse_blob(blob)
        except BlobError as err:
            errors[err.errtype] += 1
            continue
        if point:
            points.append(point)
    return points, errors


def read_archive(directory=ARCHIVE):
    """Every fix in the archive, deduplicated and sorted by time.

    Returns (Path, stats). The rotated copies overlap heavily, so `stats['duplicate']` is
    normally a large fraction of `stats['parsed']` — that is the archive being what it is,
    not a fault.
    """
    stats = Counter()
    seen = set()
    points = []
    for name in sorted(os.listdir(directory)):
        path = os.path.join(directory, name)
        if not os.path.isfile(path):
            continue
        got, errors = read_file(path)
        stats['files'] += 1
        stats['parsed'] += len(got)
        stats.update(errors)
        for point in got:
            key = (point.ts, point.lat, point.long)
            if key in seen:
                stats['duplicate'] += 1
                continue
            seen.add(key)
            points.append(point)
    points.sort(key=lambda p: p.ts)
    stats['fixes'] = len(points)
    return Path(points), stats


def by_day(points, tz_offset=2):
    """{'YYYY-MM-DD': Path} keyed by *local* day, fixes left in UTC."""
    days = {}
    for point in points:
        day = (ts2dt(point.ts) + timedelta(hours=tz_offset)).strftime('%Y-%m-%d')
        days.setdefault(day, Path()).append(point)
    return days


def travelled(points):
    """Metres along the track, and the straight line from first to last fix."""
    along = sum(points[i-1].distance_to(points[i]) for i in range(1, len(points)))
    return along, points[0].distance_to(points[-1]) if len(points) > 1 else 0.0


def holes(points, min_minutes=30):
    """Breaks in the feed longer than `min_minutes`, as (start, end, minutes, nm jumped).

    Two kinds of break exist and only one is interesting. The tracker's GSM session restarts
    for about nine minutes every two hours right through the summer, which is why the default
    threshold is well above that. What matters is a break the boat *moved* across: the line
    drawn over it is interpolation, and it must not be uploaded as though it were track.
    """
    out = []
    for i in range(1, len(points)):
        minutes = (ts2dt(points[i].ts) - ts2dt(points[i-1].ts)).total_seconds() / 60
        if minutes > min_minutes:
            out.append((points[i-1], points[i], minutes,
                        points[i-1].distance_to(points[i]) / 1852))
    return out


def speeds(points):
    """(95th percentile, maximum) of the speed the *tracker itself* reported, in knots.

    Independent of the positions, and the cheapest evidence there is that a day of movement
    was not the boat: 40 knots is a car, and Solveig does not do 40 knots. The percentile is
    there because GPS speed spikes on single fixes.
    """
    kn = sorted(p.speed / 0.514444 for p in points if p.speed is not None)
    if not kn:
        return 0.0, 0.0
    return kn[int(len(kn) * 0.95) - 1], kn[-1]


def match_photos(points, photos, tz_offset=2, max_minutes=30):
    """Pair each geotagged photograph with the tracker fix nearest it in time.

    Returns [(record, fix, metres apart)], skipping photographs with no position, no time,
    or no fix within `max_minutes`. The distance is the check: a photograph taken aboard sits
    on the track, one taken ashore sits off it by the length of a walk, and one taken on a
    different journey altogether sits off it by miles.

    **EXIF times are local and carry no timezone** (`../TRACKS-2021.md`); the tracker is UTC.
    Comparing them unshifted matches a photograph against where the boat was two hours
    earlier, which on a passage is ten miles away and reads as a contradiction that is not
    there.
    """
    out = []
    for rec in photos:
        if rec.get('lat') is None or not rec.get('time'):
            continue
        try:
            taken = datetime.strptime(rec['time'][:19], '%Y-%m-%dT%H:%M:%S')
        except ValueError:
            continue
        utc = taken - timedelta(hours=tz_offset)
        fix = min(points, key=lambda p: abs((ts2dt(p.ts) - utc).total_seconds()))
        off = abs((ts2dt(fix.ts) - utc).total_seconds()) / 60
        if off > max_minutes:
            continue
        out.append((rec, fix, Point(rec['lat'], rec['lon']).distance_to(fix)))
    return out


def thin(points, min_dist=25, min_secs=600):
    """Drop fixes within `min_dist` metres *and* `min_secs` seconds of the last one kept.

    A fix every ~17 seconds is far denser than the journey needs; a day at anchor is 5 000
    fixes of the same berth. Both endpoints are always kept, so the day's start and end times
    survive the thinning - the importer times the fix off the last point.

    The interval is what governs a stationary boat, and it wants to be generous: at 60
    seconds an anchored day still contributes 1 440 points of jitter. At 600 it contributes
    a hundred-odd, while a passage is unaffected - at 5 knots the boat covers the 25 metres
    in ten seconds, so moving stretches are governed by distance and keep their detail.
    """
    if len(points) < 3:
        return Path(points)
    kept = Path([points[0]])
    for point in points[1:-1]:
        if (point.distance_to(kept[-1]) < min_dist
                and point.time_delta(kept[-1]).total_seconds() < min_secs):
            continue
        kept.append(point)
    kept.append(points[-1])
    return kept


def stops(points, radius=50, minutes=30):
    """Runs of fixes where the boat stayed inside `radius` for at least `minutes`.

    Returned as (first, last) index pairs. This is deliberately cruder than
    `point.BoatPosData`, which classifies a stop as mooring or anchorage and runs the anchor
    alarm off it: all that is wanted here is where a leg ends.
    """
    out = []
    i, n = 0, len(points)
    while i < n:
        j = i
        while j + 1 < n and points[j+1].distance_to(points[i]) < radius:
            j += 1
        if (ts2dt(points[j].ts) - ts2dt(points[i].ts)).total_seconds() >= minutes * 60:
            out.append((i, j))
            i = j + 1
        else:
            i += 1
    return out


def segments(points, hours=2, radius=50, stop_minutes=30, gap_minutes=30,
             min_leg_minutes=30, min_leg_m=1852, min_leg_kn=0.5):
    """Split a track into the legs that should each become one journey fix.

    The owner's rule: **one fix for each stop, plus one every `hours` clock hours under way.**
    Since one GPX is one fix timestamped at its **last** point, that is a cut at each of:

    * the moment the boat arrives somewhere and stays — the fix that dates the stop;
    * each clock hour divisible by `hours`, but only once the leg is worth reporting: half an
      hour and a mile of it, which is the daemon's own `clock_hour_logic`. Without that a boat
      leaving a berth at 11:58 files a two-minute leg;
    * a break in the feed, which must never be spanned — the line across it is interpolation.

    Time at the berth is not a leg. A stop contributes the arrival fix and nothing else, so a
    day that never moved yields nothing rather than a day's worth of anchor jitter.

    `min_leg_kn` catches what the stop detector cannot. A boat swinging round its anchor
    never holds still inside `radius` for half an hour, so the drift is not seen as a stop —
    but it is not a passage either, and without the speed floor it is filed as a leg that
    covered a tenth of a mile in eight hours. Half a knot is the daemon's own threshold for
    deciding the boat has stopped.
    """
    if len(points) < 2:
        return []
    starts = {i for i, _ in stops(points, radius, stop_minutes)}
    ends = {j for _, j in stops(points, radius, stop_minutes)}
    legs, leg = [], [points[0]]

    def close():
        if len(leg) < 2 or leg[0].distance_to(leg[-1]) < radius:
            return
        hrs = (ts2dt(leg[-1].ts) - ts2dt(leg[0].ts)).total_seconds() / 3600
        along, _ = travelled(leg)
        # A leg of no elapsed time is a GPS artefact, and it is also the one shape the speed
        # floor below cannot judge, having nothing to divide by.
        if hrs <= 0 or along / 1852 / hrs < min_leg_kn:
            return
        legs.append(Path(leg))

    for i in range(1, len(points)):
        prev, point = points[i-1], points[i]
        broken = (ts2dt(point.ts) - ts2dt(prev.ts)).total_seconds() > gap_minutes * 60
        if broken or i in starts:
            # The arrival is the fix that dates the stop — but not across a break, where
            # appending it would draw the leg over water the tracker never recorded.
            if i in starts and not broken:
                leg.append(point)
            close()
            leg = [point]
            continue
        if i - 1 in ends:                       # under way again after a stop
            close()
            leg = [prev]
        leg.append(point)
        crossed = ts2dt(point.ts).hour % hours == 0 and ts2dt(prev.ts).hour != ts2dt(point.ts).hour
        worth_it = ((ts2dt(point.ts) - ts2dt(leg[0].ts)).total_seconds() >= min_leg_minutes*60
                    and leg[0].distance_to(point) >= min_leg_m)
        if crossed and worth_it:
            close()
            leg = [point]
    close()
    return legs


def summary_rows(days, min_dist=25, min_secs=600, tz_offset=2):
    """One row per day, distances measured on the *thinned* track.

    Measuring the raw track counts GPS jitter as travel: 5 000 fixes of a boat sitting at
    anchor accumulate close to a mile a day, which is enough to make every stationary day
    look like a short passage. Times are local, to match the day the row is filed under.
    """
    for day in sorted(days):
        points = days[day]
        along, direct = travelled(thin(points, min_dist, min_secs))
        local = [ts2dt(p.ts) + timedelta(hours=tz_offset) for p in (points[0], points[-1])]
        kn95, kn_max = speeds(points)
        yield {
            'day': day,
            'fixes': len(points),
            'from': local[0].strftime('%H:%M'),
            'to': local[1].strftime('%H:%M'),
            'along_nm': along / 1852,
            'direct_nm': direct / 1852,
            'kn95': kn95,
            'kn_max': kn_max,
            'lat': points[-1].lat,
            'lon': points[-1].long,
        }


def write_eml(outbox, filename, gpx, leg, day):
    """One message per leg for the importer, which takes GPX by email and nothing else.

    The body says where the geometry came from because `creator` alone is easy to miss, and
    because a track recovered from a server log five years after the fact deserves saying so.
    """
    from email.message import EmailMessage
    os.makedirs(outbox, exist_ok=True)
    along, _ = travelled(leg)
    msg = EmailMessage()
    msg['From'], msg['To'] = config.FROM, TO
    msg['Subject'] = config.subject(
        f'{day} ({leg[0].ts[11:16]}-{leg[-1].ts[11:16]} UTC)')
    msg.set_content(
        f'Track for S/Y {config.BOAT_NAME}, {day}.\n\n'
        f'{len(leg)} points, {leg[0].ts} to {leg[-1].ts} UTC, {along/1852:.2f} nm.\n\n'
        'These are real GPS positions from the GSM/GPS tracker carried aboard in 2021,\n'
        'recovered from the raw server log the tracking daemon wrote at the time. The\n'
        'positions and the times are the tracker\'s own; nothing is interpolated, and legs\n'
        'are cut wherever the tracker lost contact so no line is drawn across a gap.\n')
    msg.add_attachment(gpx.encode(), maintype='application', subtype='gpx+xml',
                       filename=filename)
    with open(os.path.join(outbox, filename.replace('.gpx', '.eml')), 'wb') as f:
        f.write(bytes(msg))


def photo_report(days, rows, tz_offset=2):
    """Per day: how far that day's photographs sit from where the tracker says the boat was.

    `exif_index.py` is the other agent's; it is only read here, and with `--locations`
    applied, so a photograph the owner has already corrected or flagged `ashore` is compared
    at the position he gave it rather than the one the camera wrote.
    """
    from boattracker.nfl import exif_index
    photos = exif_index.apply_manual(exif_index.load(), exif_index.MANUAL).values()
    by_date = {}
    for rec in photos:
        if rec.get('time'):
            by_date.setdefault(rec['time'][:10], []).append(rec)

    print(f'\n{"day":11s} {"photos":>6s} {"median m":>9s} {"worst m":>9s}  '
          f'{"ashore":>6s}  worst photograph')
    for r in rows:
        got = match_photos(days[r['day']], by_date.get(r['day'], []), tz_offset)
        if not got:
            print(f"{r['day']:11s} {'-':>6s}")
            continue
        got.sort(key=lambda x: x[2])
        worst = got[-1]
        median = got[len(got)//2][2]
        ashore = sum(1 for rec, _, _ in got if rec.get('ashore'))
        print(f"{r['day']:11s} {len(got):6d} {median:9.0f} {worst[2]:9.0f}  "
              f"{ashore:6d}  {os.path.basename(worst[0]['path'])}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--archive', default=ARCHIVE)
    ap.add_argument('--from', dest='lo', help='first local day (YYYY-MM-DD)')
    ap.add_argument('--to', dest='hi', help='last local day')
    ap.add_argument('--tz-offset', type=float, default=2,
                    help='hours to add to UTC to get the local day (default 2, CEST)')
    ap.add_argument('--moved', type=float, default=0.0,
                    help='only list days that travelled at least this many nm')
    ap.add_argument('--gaps', type=float, metavar='MINUTES', nargs='?', const=30,
                    help='list breaks in the feed instead of days (default 30 minutes)')
    ap.add_argument('--photos', action='store_true',
                    help='check each day against the geotagged photographs of that day')
    ap.add_argument('--min-dist', type=float, default=25, help='thinning distance, metres')
    ap.add_argument('--min-secs', type=float, default=600, help='thinning interval, seconds')
    ap.add_argument('--outbox', help='also write one .eml per leg, ready for sendmail')
    ap.add_argument('--hours', type=int, default=2,
                    help='clock-hour interval for a fix under way (default 2)')
    ap.add_argument('--out', default=GPXDIR)
    ap.add_argument('--prefix', default='tracker2021')
    ap.add_argument('--write', action='store_true', help='write one GPX per listed day')
    a = ap.parse_args()

    points, stats = read_archive(a.archive)
    print(f"{stats['files']} files, {stats['parsed']} blobs parsed, "
          f"{stats['duplicate']} duplicates dropped, {stats['fixes']} distinct fixes")
    errors = {k: v for k, v in stats.items()
              if k not in ('files', 'parsed', 'duplicate', 'fixes')}
    if errors:
        print('unparsed: ' + ', '.join(f'{k} {v}' for k, v in sorted(errors.items())))
    if not points:
        return
    print(f'{points[0].ts} .. {points[-1].ts} UTC\n')

    if a.gaps:
        found = holes(points, a.gaps)
        print(f'{"from (UTC)":19s} {"to (UTC)":19s} {"hours":>6s} {"nm":>6s}')
        for start, end, minutes, nm in found:
            print(f'{start.ts:19s} {end.ts:19s} {minutes/60:6.1f} {nm:6.2f}'
                  + ('   <- moved across the break' if nm > 1 else ''))
        crossed = sum(nm for *_, nm in found if nm > 1)
        print(f'\n{len(found)} breaks over {a.gaps:.0f} minutes, '
              f'{crossed:.1f} nm of them crossed while out of contact')
        return

    days = by_day(points, a.tz_offset)
    rows = [r for r in summary_rows(days, a.min_dist, a.min_secs, a.tz_offset)
            if (not a.lo or r['day'] >= a.lo) and (not a.hi or r['day'] <= a.hi)
            and r['along_nm'] >= a.moved]
    print(f'{"day":11s} {"fixes":>6s} {"first":>5s} {"last":>5s} '
          f'{"track":>7s} {"line":>7s} {"kn95":>5s} {"kn":>5s}  end position')
    total = 0.0
    for r in rows:
        total += r['along_nm']
        print(f"{r['day']:11s} {r['fixes']:6d} {r['from']:>5s} {r['to']:>5s} "
              f"{r['along_nm']:7.1f} {r['direct_nm']:7.1f} {r['kn95']:5.1f} {r['kn_max']:5.1f}"
              f"  {r['lat']:.5f}, {r['lon']:.5f}")
    print(f'\n{len(rows)} days, {total:.1f} nm along track')

    if a.photos:
        photo_report(days, rows, a.tz_offset)
        return

    if not a.write:
        print('(dry run - pass --write to save one GPX per day)')
        return
    os.makedirs(a.out, exist_ok=True)
    written = 0
    for r in rows:
        kept = thin(days[r['day']], a.min_dist, a.min_secs)
        legs = segments(kept, a.hours)
        for leg in legs:
            # Both ends in the name: two legs of one day can share an end minute - a stop
            # arrival and the clock hour that follows it - and one silently overwrote the
            # other when the name carried only the end.
            start = ts2dt(leg[0].ts) + timedelta(hours=a.tz_offset)
            end = ts2dt(leg[-1].ts) + timedelta(hours=a.tz_offset)
            name = (f"{r['day']} tracker feed, {ts2dt(leg[0].ts):%H:%M}-"
                    f"{ts2dt(leg[-1].ts):%H:%M} UTC")
            fn = f"{a.prefix}-{r['day']}-{start:%H%M}-{end:%H%M}.gpx"
            gpx = leg.export_gpx(name=name, creator=CREATOR)
            with open(os.path.join(a.out, fn), 'w') as f:
                f.write(gpx)
            if a.outbox:
                write_eml(a.outbox, fn, gpx, leg, r['day'])
            written += 1
        print(f"{r['day']}: {len(legs)} legs, "
              f"{sum(len(leg) for leg in legs)} of {r['fixes']} fixes")
    print(f'\n{written} files written to {a.out}')


if __name__ == '__main__':
    main()
