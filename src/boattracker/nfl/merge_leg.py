"""Merge everything the journey and the local exports hold for one leg into one timed track.

**The owner's rule, 2026-08-14: one fix, one leg, a timestamp on every vertex.** A leg runs
from one significant stop to the next, and the diary headings are where those stops are
recorded — `~/solveig/diary-202401.md` covers 2024 and 2025 despite its name, and under each
`## <weekday> <date> - <place> - <place>` heading the old tracker's own stop detection has
already written `arrived at anchorage` / `departed from anchorage` lines with timestamps.

## Why a leg needs merging at all

A single leg is typically on the journey as **several** fixes, and none of them is wrong:

* the **tracker** leg — good times, coarse positions, and straight chords wherever it lost
  GSM coverage;
* one or more **plotter fills** uploaded earlier to cover those chords, each landing as its
  own fix *inside* the tracker leg's window, which is what makes the map draw the leg twice
  and jump backwards between them (`find_backtracks.py --windows`);
* stationary stubs of a few metres.

2024-02-24, 2024-03-03 and 2024-04-03 are each **one leg** by the diary, held as 11, 5 and 10
fixes. Filling the chords again is not the answer — `replace_tracker_chords.py` will tell you
that geometry is already on the journey. Rebuilding the leg as one track is.

## What it does

`plotter for position, tracker for time`, which is the precedence rule in `../SOURCES.md`:

1. **`collect`** every *timed* vertex the journey holds in the leg's window, from every fix,
   in time order, with one moment recorded twice collapsed to one.
2. **`gaps`** finds what is still missing — a jump over the threshold between consecutive
   vertices. The owner's rule is **one nautical mile**; below that, a difference is GPS noise
   and not worth a message.
3. **`time_across`** dates a plotter slice spliced into a gap, spreading the gap's own end
   times along it **by distance**, so the times come from the tracker's clock rather than
   being invented.
4. **`splice`** puts the slices in and guarantees the result is **strictly increasing in
   time**. That last part is not decoration: a vertex out of order is exactly the defect
   this whole exercise exists to remove.

The output is one GPX for the leg. Sending it and deleting what it replaces are separate
steps, in that order — `../IMPROVE-TRACKS.md` step 5, and export to `../nfl-retired/` first.
"""

import argparse
import math
import os
from datetime import UTC

from boattracker import (
    config,  # noqa: E402
    files,
)

MIN_GAP_NM = 1.0
SAME_PLACE_M = 400.0

# The importer derives the displayed source label from `creator`, so a merged leg must not
# claim to be a plain chartplotter export — it is not one, and mislabelling it would hide
# that its positions and its times come from different instruments.
CREATOR = ('merged leg: chartplotter positions where available, on-board GPS/GSM tracker '
           'timestamps throughout, rebuilt as one fix for one leg')


def nm(a, b):
    """Nautical miles between two (lat, lon) pairs."""
    R = 3440.065
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    h = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(b[1] - a[1]) / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(h))


def collect(lines, t0, t1, same_place_m=SAME_PLACE_M):
    """Every timed vertex in [t0, t1] across all lines, in time order, deduplicated.

    Untimed vertices (epoch 0) are dropped: a merged leg is defined by its times, and there
    is nothing to place an untimed point at in the sequence.

    Deduplication matters because the tracker and a plotter fill both record the arrival.
    Two vertices are one when they share an instant *and* sit within `same_place_m`.

    That tolerance is **400 m, not a few metres**, because the two instruments differ by more
    than rounding: on 2024-04-03 the tracker and the plotter both record 13:40:05 a full
    0.11 nm apart, and keeping both puts a 200 m wobble in the line that reads as 18.9 kn.
    The *first* of such a pair survives, and `journey_lines` lists chartplotter lines first,
    so the better position wins — the precedence rule in `../SOURCES.md`. A pair further apart
    than this is a real contradiction and is deliberately left visible.
    """
    out = []
    for line in lines:
        for p in line:
            if len(p) < 3 or not p[2]:
                continue
            if t0 <= p[2] <= t1:
                out.append((p[0], p[1], p[2]))
    out.sort(key=lambda p: p[2])
    kept = []
    for p in out:
        if kept and p[2] == kept[-1][2] and nm(p[:2], kept[-1][:2]) * 1852 <= same_place_m:
            continue
        kept.append(p)
    return kept


def gaps(points, min_nm=MIN_GAP_NM):
    """Indices i where the jump from points[i] to points[i+1] is missing data.

    The owner's threshold, 2026-08-14: **more than a nautical mile between two consecutive
    vertices**, and only then if better data exists. Deviation is deliberately not part of
    this — 9 to 11 m between two records is GPS noise, not a better position.
    """
    return [i for i in range(len(points) - 1)
            if nm(points[i][:2], points[i + 1][:2]) >= min_nm]


def time_across(slice_points, t_start, t_end):
    """Date a spliced slice from the gap's own end times, spread by distance along it.

    Distance rather than point count, because plotter sampling is not uniform: spacing runs
    400 m to 1100 m on the 2023-24 crops, so counting points would hurry the boat through the
    densely-sampled parts and slow her through the sparse ones.

    The times are therefore the *tracker's*, interpolated — not invented, which is the whole
    point of the precedence rule.
    """
    if not slice_points:
        return []
    if len(slice_points) == 1:
        return [(slice_points[0][0], slice_points[0][1], t_start)]
    steps = [nm(slice_points[i][:2], slice_points[i + 1][:2])
             for i in range(len(slice_points) - 1)]
    total = sum(steps)
    out, run = [], 0.0
    for i, p in enumerate(slice_points):
        f = 0.0 if total == 0 else run / total
        out.append((p[0], p[1], int(t_start + (t_end - t_start) * f)))
        if i < len(steps):
            run += steps[i]
    out[-1] = (out[-1][0], out[-1][1], int(t_end))
    return out


def splice(points, slices):
    """Insert each slice into its gap, keeping the result strictly increasing in time.

    `slices` maps a gap index (as returned by `gaps`) to the plotter points that fill it,
    endpoints included; those endpoints are dropped in favour of the vertices already there,
    so the join carries no duplicate.

    **Strictly increasing is enforced, not assumed.** Interpolating along a slice that
    doubles back can otherwise emit a vertex a millisecond behind its predecessor, and a
    vertex out of order is the defect this module exists to remove.
    """
    if not slices:
        return list(points)
    out = []
    for i, p in enumerate(points):
        out.append(p)
        if i in slices:
            filler = time_across(slices[i], p[2], points[i + 1][2])
            out.extend(filler[1:-1])
    fixed, last = [], None
    for p in out:
        t = p[2] if last is None or p[2] > last else last + 1
        fixed.append((p[0], p[1], int(t)))
        last = t
    return fixed


MAX_KNOTS = 12.0
MAX_DETOUR = 1.6

def plausible_slice(slice_nm, gap_nm, hours, max_knots=MAX_KNOTS, max_detour=MAX_DETOUR):
    """Could the boat have sailed this slice across this gap, in this time?

    `replace_tracker_chords.covering_slice` accepts any slice whose two ends fall within a
    mile of the gap's ends, **on any segment of the named track** — and passing `--tracks` to
    `find_gaps.source_segments` disables its date filter, so a segment from a different month
    is eligible. Nothing else stops the wrong water being spliced in.

    Two independent tests, because neither catches the other:

    * **detour** — sailed track is longer than the straight line, but not endlessly. Tacking
      and headlands justify some; 2.4x does not.
    * **speed** — a slice the right length is still wrong if there was no time to sail it.

    Both were needed on 2024-04-03, where 11.11 nm of `Track 4 s69` was offered to bridge a
    4.54 nm gap of 52 minutes: 12.8 kn, which this boat does not do.
    """
    if hours <= 0 or gap_nm <= 0:
        return False
    if slice_nm > gap_nm * max_detour:
        return False
    return slice_nm / hours <= max_knots

def implausible_steps(points, max_knots=MAX_KNOTS):
    """Consecutive merged vertices the boat could not have sailed between.

    **Merging does not resolve a contradiction between sources; it moves it inside one
    line.** Two records that disagree about where the boat was at a given minute produce a
    jump *between fixes* before the merge, which `find_backtracks.py` reports — and the same
    error *inside* a single line afterwards, which it cannot see. So the merge has to check
    its own output before anything is sent.

    2024-04-03 is the case: two of its pairs are not GSM dropouts but genuine contradictions,
    and merging them gave steps implying 67 and 76 kn.
    """
    out = []
    for i in range(len(points) - 1):
        d = nm(points[i][:2], points[i + 1][:2])
        h = (points[i + 1][2] - points[i][2]) / 3600000.0
        if d <= 0 or h <= 0:
            continue
        if d / h > max_knots:
            out.append((i, d, h, d / h))
    return out

def retime(points, backbone, max_m=3000.0):
    """Re-date plotter points from the tracker's clock, by where the tracker says it was.

    **The plotter records no time at all.** Every timestamp on Raymarine data here was
    assigned — by an export script or by hand — and that is where the impossible speeds come
    from. On 2024-04-03 every implausible step in the merged leg had at least one Raymarine
    end and five of six had both, alternating between two fixes, which is two assigned
    timestamps overlapping so the line ping-pongs between two parallel tracks. No step was
    tracker-to-tracker.

    The precedence rule appoints the tracker the authority on time, so each plotter point
    takes the time the tracker line carries at the place the plotter says the boat was.
    Checked against a known case this is close: it put the 2023-06-05 fragment's end at 02:56
    against its own stamp of 02:51.

    A point further than `max_m` from the backbone is **dropped, not guessed** — nothing on
    the tracker line speaks for water it never went near, and guessing is the original sin
    here. Output is sorted by the new times.
    """
    if not backbone or len(backbone) < 2:
        return []
    out = []
    for p in points:
        best = (float('inf'), None)
        for i in range(len(backbone) - 1):
            a, b = backbone[i], backbone[i + 1]
            d = _point_to_edge_m(p[:2], a[:2], b[:2])
            if d >= best[0]:
                continue
            seg = nm(a[:2], b[:2])
            f = 0.0 if seg == 0 else min(1.0, max(0.0, nm(a[:2], p[:2]) / seg))
            best = (d, int(a[2] + (b[2] - a[2]) * f))
        if best[1] is not None and best[0] <= max_m:
            out.append((p[0], p[1], best[1]))
    out.sort(key=lambda q: q[2])
    return out

def _point_to_edge_m(pt, a, b):
    """Metres from pt to the segment a-b, flat-earth over the short distances involved."""
    k = 111320.0
    ky = k * math.cos(math.radians(pt[0]))
    ax, ay = (a[1] - pt[1]) * ky, (a[0] - pt[0]) * k
    bx, by = (b[1] - pt[1]) * ky, (b[0] - pt[0]) * k
    dx, dy = bx - ax, by - ay
    t = 0.0 if dx == dy == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / (dx * dx + dy * dy)))
    return math.hypot(ax + t * dx, ay + t * dy)

def smooth_joins(points, max_knots=MAX_KNOTS):
    """Re-time only the vertices whose timing is impossible, leaving the rest alone.

    **The 2024-04-02/03 defect.** That passage is eight slices of one segment, `Track 4 s88`,
    in the correct point order — nothing is in the wrong place. But adjacent slices carry
    *assigned* times that overlap by a couple of minutes (`…971576` starts 20:32:45 while
    `…971575` runs to 20:34:57), so a join crosses one s88 point spacing of ~850 m in two
    minutes and reads as 12 to 20 kn.

    The repair is local by design. A bad edge is widened to the nearest vertex on each side
    that is *itself* consistent, and only the vertices strictly between those two anchors are
    re-timed, by cumulative distance. Every vertex whose timing already made sense keeps the
    time it had, and the leg's own endpoints never move — this is a correction, not a
    smoothing, and re-timing a whole passage to a uniform speed would erase the real
    variation in it.

    Positions are never touched.
    """
    if len(points) < 3:
        return list(points)
    pts = list(points)

    def bad(i):
        d = nm(pts[i][:2], pts[i + 1][:2])
        h = (pts[i + 1][2] - pts[i][2]) / 3600000.0
        if h <= 0:
            return d > 0
        return d / h > max_knots

    # Bounded, because redistribution cannot always succeed: if the two anchors are
    # themselves too close in time for the distance between them, the edge stays bad however
    # the interior is spread, and an unbounded loop re-times the same window forever. That is
    # not hypothetical — it hung on the real 2024-04-03 leg, and `test_merge_leg.py` pins it.
    tried = set()
    changed = True
    while changed:
        changed = False
        for i in range(len(pts) - 1):
            if not bad(i):
                continue
            lo, hi = i, i + 1
            while lo > 0 and bad(lo - 1):
                lo -= 1
            while hi < len(pts) - 1 and bad(hi):
                hi += 1
            if hi - lo < 2:            # nothing between the anchors to move
                hi = min(hi + 1, len(pts) - 1)
            if hi - lo < 2 or (lo, hi) in tried:
                continue          # cannot be fixed by redistribution; leave it and move on
            tried.add((lo, hi))
            steps = [nm(pts[j][:2], pts[j + 1][:2]) for j in range(lo, hi)]
            total = sum(steps)
            t0, t1 = pts[lo][2], pts[hi][2]
            run = 0.0
            for k in range(1, hi - lo):
                run += steps[k - 1]
                f = 0.0 if total == 0 else run / total
                pts[lo + k] = (pts[lo + k][0], pts[lo + k][1], int(t0 + (t1 - t0) * f))
            changed = True
            break
    # guarantee strict increase, which an inverted pair can otherwise survive
    out, last = [], None
    for p in pts:
        t = p[2] if last is None or p[2] > last else last + 1
        out.append((p[0], p[1], int(t)))
        last = t
    return out

def reorder_times_by_segment(points, segment, tol_m=60.0):
    """Make time order follow the source segment's own point order.

    **The residual 2024-04-03 defect.** Two adjacent slices of `Track 4 s88` carry assigned
    time windows that overlap, so sorting the merged leg by time interleaves them and the
    drawn path ping-pongs between two parts of the segment — 20:30:29 from `…971575`,
    20:32:45 from `…971576`, 20:34:57 from `…971575` again. `smooth_joins` cannot help there:
    the *order* is wrong, not the spacing.

    The plotter segment records the order the boat actually sailed, so it is the authority
    here. Vertices lying on it are put into its index order and handed the timestamps back in
    ascending order — **the same times, on the right vertices**. Nothing is invented and
    nothing is discarded, which is what makes this safe to apply to assigned times.

    Vertices further than `tol_m` from the segment are left alone: tracker positions off the
    plotter's track say nothing about its order.
    """
    if not segment or len(points) < 2:
        return list(points)
    on = []
    for i, p in enumerate(points):
        j = min(range(len(segment)), key=lambda k: nm(p[:2], segment[k]))
        if nm(p[:2], segment[j]) * 1852 <= tol_m:
            on.append((j, i))
    if len(on) < 2:
        return list(points)
    idxs = [i for _, i in on]
    times = sorted(points[i][2] for i in idxs)
    out = list(points)
    for (seg_i, orig_i), t in zip(sorted(on), times):
        out[orig_i] = (points[orig_i][0], points[orig_i][1], int(t))
    return out

def gpx(points, name, creator=CREATOR):
    """One GPX for the merged leg, **keeping each vertex's own time**.

    `leg_export.build` is the usual writer in this project and is the wrong one here: it
    re-times points across the leg by cumulative distance. That is correct when the source
    has no times of its own — which is the normal Raymarine case — and destructive here,
    where every vertex already carries the tracker's real clock and the boat's speed varied
    along the way. `reimport_journey.gpx` already writes per-vertex times, so this is its
    format with a creator that says what the leg actually is.
    """
    from boattracker.nfl import reimport_journey
    return reimport_journey.gpx(name, [(p[0], p[1], p[2]) for p in points], creator)

def eml(gpx_text, name, filename):
    """The MIME message for the importer, wrapping a GPX that already carries its times.

    `leg_export.build` writes both the GPX and the .eml, but its GPX is re-timed by distance
    (see `gpx` above), so only the envelope is reusable. The addresses come from there rather
    than being repeated: `FROM` must be the authorised sender or the importer's address check
    and SPF both reject it.
    """
    from email.message import EmailMessage

    from boattracker.nfl import leg_export as LE
    m = EmailMessage()
    m['From'] = LE.FROM
    m['To'] = LE.TO
    m['Subject'] = config.subject(name)
    m.set_content(
        f'Track for S/Y {config.BOAT_NAME}: {name}\n\n'
        'One leg, rebuilt as a single track. Positions are from a Raymarine chartplotter\n'
        'where it recorded them and from the on-board GPS/GSM tracker elsewhere; every\n'
        'timestamp is the tracker\'s own, so the times are recorded rather than estimated.\n'
        'This replaces the several fixes that previously held the same leg.\n')
    m.add_attachment(gpx_text.encode(), maintype='application', subtype='gpx+xml',
                     filename=filename)
    return bytes(m)

def journey_lines(doc, t0, t1):
    """Rendered lines whose fix falls in the window, as [(lat, lon, ms), ...].

    **Chartplotter lines come first**, and that ordering is load-bearing: `collect` keeps the
    first of two vertices recorded at one instant in one place, so listing the plotter first
    is how the precedence rule in `../SOURCES.md` — the plotter carries the better position —
    gets applied to a same-instant pair. On 2024-04-03 the tracker and the plotter both
    record 13:40:05, 0.11 nm apart, which is simply the difference in their precision.
    """
    times = {f['properties']['fixId']: f['properties'].get('timeMs')
             for f in doc['geojson']['features'] if f['geometry']['type'] == 'Point'}
    src = {f['properties']['fixId']: f['properties'].get('source')
           for f in doc['geojson']['features'] if f['geometry']['type'] == 'Point'}
    plotter, other = [], []
    for f in doc['geojson']['features']:
        if f['geometry']['type'] != 'LineString':
            continue
        fid = f['properties'].get('fixId')
        ms = times.get(fid)
        if ms is None or not (t0 <= ms <= t1):
            continue
        line = [(c[1], c[0], c[2] if len(c) > 2 else 0)
                for c in f['geometry']['coordinates']]
        (plotter if src.get(fid) == 'Raymarine GPX Export' else other).append(line)
    return plotter + other


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--snapshot', required=True)
    ap.add_argument('--from', dest='t0', required=True,
                    help='leg start, ISO UTC, e.g. 2024-02-24T09:30:00')
    ap.add_argument('--to', dest='t1', required=True, help='leg end, ISO UTC')
    ap.add_argument('--min-gap', type=float, default=MIN_GAP_NM,
                    help='nm; a jump at least this long is missing data (default 1.0)')
    ap.add_argument('--fill', action='store_true',
                    help='splice local plotter track into the gaps that remain')
    ap.add_argument('--tracks', help='comma-separated plotter track names to draw slices '
                                     'from, e.g. "Track 4"')
    ap.add_argument('--smooth', action='store_true',
                    help='re-time only the joins whose implied speed is impossible, leaving '
                         'every consistent vertex alone')
    ap.add_argument('--write', metavar='PATH', help='write the merged leg as GPX')
    ap.add_argument('--eml', metavar='PATH', help='also write the MIME message to send')
    ap.add_argument('--name', help='leg name for the GPX, e.g. "2024-02-24 Ormos Vathy - '
                                   'Astypalea Chora"')
    a = ap.parse_args()

    from datetime import datetime
    iso = lambda s: int(datetime.fromisoformat(s).replace(
        tzinfo=UTC).timestamp() * 1000)
    t0, t1 = iso(a.t0), iso(a.t1)
    doc = files.read_json(a.snapshot)
    lines = journey_lines(doc, t0 - 86400000, t1 + 86400000)
    pts = collect(lines, t0, t1)
    g = gaps(pts, a.min_gap)
    total = sum(nm(pts[i][:2], pts[i + 1][:2]) for i in range(len(pts) - 1))
    print(f'{len(lines)} journey line(s) touch the window; '
          f'{len(pts)} timed vertices merge to {total:.2f} nm')
    if not pts:
        return
    show = lambda ms: datetime.fromtimestamp(ms / 1000, UTC).strftime('%H:%M:%SZ')
    print(f'   {show(pts[0][2])} .. {show(pts[-1][2])}')
    print(f'{len(g)} gap(s) of {a.min_gap}+ nm remain, which is what plotter track would fill:')
    for i in g:
        print(f'   {show(pts[i][2])} -> {show(pts[i + 1][2])}  '
              f'{nm(pts[i][:2], pts[i + 1][:2]):6.2f} nm  '
              f'{pts[i][0]:.5f},{pts[i][1]:.5f} -> {pts[i+1][0]:.5f},{pts[i+1][1]:.5f}')
    if a.fill and g:
        from boattracker.nfl import find_gaps as FG
        from boattracker.nfl import replace_tracker_chords as RT
        tracks = a.tracks.split(',') if a.tracks else None
        # Pass the leg's own dates. Naming a track narrows *which* track is searched; it says
        # nothing about when, and without a window a segment from any month of it is eligible
        # — which is how slices months away were offered for this leg before 2026-08-15.
        win = (a.t0[:10], a.t1[:10])
        segs = FG.source_segments(tracks=tracks, window=win, strict_dates=True)
        slices, filled = {}, 0.0
        for i in g:
            got = RT.covering_slice(segs, pts[i], pts[i + 1])
            if not got:
                print(f'   no plotter slice for the {show(pts[i][2])} gap')
                continue
            _, fn, tname, si, sl, snm = got
            gap_nm = nm(pts[i][:2], pts[i + 1][:2])
            hours = (pts[i + 1][2] - pts[i][2]) / 3600000.0
            if not plausible_slice(snm, gap_nm, hours):
                print(f'   REJECTED {tname} s{si} for the {show(pts[i][2])} gap: '
                      f'{snm:.2f} nm of track across {gap_nm:.2f} nm in {hours:.2f} h '
                      f'= {snm/hours if hours else 0:.1f} kn')
                continue
            slices[i] = sl
            filled += gap_nm
            print(f'   filling {show(pts[i][2])} from {tname} s{si} ({fn}), '
                  f'{len(sl)} points, {snm:.2f} nm of track')
        if slices:
            pts = splice(pts, slices)
            after = sum(nm(pts[i][:2], pts[i + 1][:2]) for i in range(len(pts) - 1))
            print(f'   filled {len(slices)} of {len(g)} gaps; leg now {len(pts)} vertices, '
                  f'{after:.2f} nm, {len(gaps(pts, a.min_gap))} gap(s) left')

    if a.smooth and a.tracks and len(a.tracks.split(',')) == 1:
        from boattracker.nfl import find_gaps as FG2
        segs2 = FG2.source_segments(tracks=[a.tracks], window=(a.t0[:10], a.t1[:10]),
                                    strict_dates=True)
        best, hits = None, 0
        for _fn, _n, _si, sp in segs2:
            c = sum(1 for p in pts if min(nm(p[:2], q) for q in sp) * 1852 <= 60)
            if c > hits:
                best, hits = sp, c
        if best and hits >= 2:
            was = len(implausible_steps(pts))
            pts = reorder_times_by_segment(pts, best)
            pts.sort(key=lambda p: p[2])
            print(f'   --smooth: {hits} vertices put into source-segment order, '
                  f'{was} unsailable step(s) -> {len(implausible_steps(pts))}')

    if a.smooth:
        before = len(implausible_steps(pts))
        pts = smooth_joins(pts)
        after = len(implausible_steps(pts))
        print(f'   --smooth: re-timed the joins, {before} unsailable step(s) -> {after}')

    bad = implausible_steps(pts)
    if bad:
        print(f'\n** {len(bad)} step(s) in the merged leg are not sailable — the sources '
              f'contradict each other and merging has moved that inside one line:')
        for i, d, h, kn in bad:
            print(f'   {show(pts[i][2])} -> {show(pts[i + 1][2])}  {d:6.2f} nm in '
                  f'{h * 60:5.1f} min = {kn:6.1f} kn')
        print('   Resolve the contradiction before sending; `find_backtracks.py` cannot see')
        print('   this once it is inside a single line.')

    if a.write:
        name = a.name or f'merged leg {a.t0} .. {a.t1}'
        with open(a.write, 'w') as fh:
            fh.write(gpx(pts, name))
        if a.eml:
            with open(a.eml, 'wb') as fh:
                fh.write(eml(gpx(pts, name), name, os.path.basename(a.write)))
            print(f'wrote {a.eml}')
        print(f'\nwrote {a.write} — {len(pts)} vertices, each with its own time.')
        print('   Send it, then delete what it replaces — export those to ../nfl-retired/')
        print('   first. See ../IMPROVE-TRACKS.md step 5.')


if __name__ == '__main__':
    main()
