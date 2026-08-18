"""Replace a GPS/GSM tracker straight line with the plotter geometry that covers it.

The 2023-2024 journey came mostly from the on-board tracker. It timestamps well and reports
live, but it is coarser than the chartplotter and stops recording outside cellphone
coverage, so offshore stretches arrive as long straight chords. Where the plotter recorded
that water, the two sources are complementary rather than competing: **plotter geometry
married to tracker times**.

That marriage is possible because journey vertices are `[lon, lat, epoch_ms]` — every
vertex carries its own timestamp, so a chord has an exact time at each end. The plotter
track between those two points can be sliced out and timestamped across that window.

## The catch, and why this is not a bulk job

Many 2023 vertices carry **epoch 0** rather than a real time — the whole Balearics and
Sardinia stretch does, including a 123.68 nm chord. Those are not tracker fixes at all;
without times at the chord ends there is nothing to interpolate between, and the bracketing
*fix* timestamps have to be used instead, which is a weaker claim. This script therefore
handles only chords with real times at both ends, and reports the rest rather than guessing.

Of 102 chords over 5 nm, 89 have plotter track available; how many of those also have usable
end times is what `--list` reports.

## What decides: the size of the gap, not the deviation

**The owner's rule, 2026-08-14.** A track is replaced when it has **a jump of more than a
nautical mile between two consecutive vertices and more precise data exists**. That is the
whole test. A mile-wide gap is missing data — the boat sailed it and nothing recorded it.

Deviation is **not** the test, and this section used to say the opposite. It argued that 25 m
can be the difference between a track passing land and not, so every chord with cover should
be replaced regardless. The owner has since ruled the other way for the small ones: three of
the four candidates on 2024-04-03 differ from the plotter by **9 to 11 metres**, which is GPS
noise rather than a better position, and re-sending a track for that costs him a message and
buys nothing.

What survives from the old reasoning is that a **two-point edge is itself a signal that data
is missing** — which is exactly what the one-mile jump test measures, and measures better.
Deviation is still reported, to say what a replacement would actually change.

## Slicing

The plotter segment is cut at its closest points to the two chord ends, and the direction is
checked — a segment can run either way relative to the chord. Uploading a whole segment when
only part of it is missing is how duplicate geometry gets created, so the slice matters.

Nothing is deleted. The tracker fix keeps its position and time; what changes is that the
straight line between two of its vertices is now also covered by a real track. If the result
looks right, the coarse line can be tidied afterwards — but check first whether the fix
carries hand-placed map corrections, as the 2025-08 bridge did.
"""
import argparse
import math
from datetime import UTC, datetime

from boattracker.nfl import find_gaps as FG
from boattracker.nfl import leg_export as LE

MIN_JUMP_NM = 1.0
# Plotter points a slice must span between the chord's two ends. This was **10**, which on a
# coarse track refuses every short chord on principle: the 2023-24 crops run 400 to 1100 m
# between points, so a 1 to 2 nm chord is three to six points. On the 2023-06-05 leg that
# withheld 23.6 nm of real detail across 15 chords, all of them covered by `Track 1 s52`
# with the ends within 69 to 350 m and real times at both. What the guard is actually for is
# refusing a slice that is only the two endpoints again, so it needs to be small.
MIN_SLICE_POINTS = 3

def replaceable(step_nm, min_jump=MIN_JUMP_NM):
    """Is a vertex-to-vertex jump this long worth replacing with better data?

    **The owner's rule, 2026-08-14**, and it replaces the deviation-based reasoning this
    module was built on: a track is replaced when it has **a jump of more than a nautical
    mile between two consecutive vertices and more precise data exists**. A gap that big is
    missing data — the boat sailed a mile or more and nothing recorded it.

    What it is *not* is a deviation test. Three of the four candidates on 2024-04-03 differ
    from the plotter by 9 to 11 metres, which is GPS noise rather than a better position, and
    re-sending a track for that costs the site's owner a message and buys nothing.
    """
    return step_nm >= min_jump

TRACKS_2023_24 = {'ToSantorini2024', 'Track 7', 'Track 1', 'Med 2023', 'Track 3', 'Track 4'}
CREATOR = ('raymarine track, positioned by the chartplotter and timed from the on-board '
           'GPS/GSM tracker fixes at each end')

def chords(d, lo, hi, min_chord, tracks):
    """(nm, fix_time, edge_index, (lat,lon,ms), (lat,lon,ms), covering_hits, fix_id)"""
    feats = d['geojson']['features']
    tms = {f['properties']['fixId']: f['properties'].get('timeMs')
           for f in feats if f['properties'].get('layer') == 'fixes'}
    # `lo`/`hi` are the caller's date range; passing them keeps a segment from another month
    # of the same track out of the candidate list. Naming a track narrows which track is
    # searched, never when it may be from.
    segs = FG.source_segments(tracks=tracks, window=(lo, hi), strict_dates=True)
    idx = FG.Index([p for _, _, _, p in segs])
    out = []
    for f in feats:
        if f['geometry']['type'] != 'LineString':
            continue
        ms = tms.get(f['properties'].get('fixId'))
        if not ms:
            continue
        t = datetime.fromtimestamp(ms/1000, UTC)
        if not (lo <= t.strftime('%Y-%m-%d') <= hi):
            continue
        v = [(c[1], c[0], c[2]) for c in f['geometry']['coordinates']]
        if len(v) >= 3 and FG.hav(v[0], v[1]) > 2.0:
            v = v[1:]
        for i in range(len(v)-1):
            step = FG.hav(v[i], v[i+1])
            if step < min_chord:
                continue
            hits = sum(1 for k in range(1, 10)
                       if idx.distance(v[i][0]+(v[i+1][0]-v[i][0])*k/10,
                                       v[i][1]+(v[i+1][1]-v[i][1])*k/10) <= 3000)
            out.append((step, t, i, v[i], v[i+1], hits, f['properties'].get('fixId')))
    out.sort(reverse=True)
    return out, segs

def journey_lines_except(d, fix_id):
    """Every rendered journey line but the one belonging to `fix_id`, as [(lat, lon), ...].

    The excluded one is the tracker leg being repaired. Counting it would be circular: its
    chord's endpoints sit on the slice by construction, so it would report cover for the very
    gap the slice exists to fill.
    """
    out = []
    for f in d['geojson']['features']:
        if f['geometry']['type'] != 'LineString':
            continue
        if f['properties'].get('fixId') == fix_id:
            continue
        out.append([(c[1], c[0]) for c in f['geometry']['coordinates']])
    return out

def already_on_journey(sl, lines, tol_m=300.0):
    """Percentage of the plotter slice that some *other* journey line already holds.

    **The check this module was missing.** It asks whether plotter cover exists for a chord;
    it never asked whether that cover had already been uploaded. On 2026-08-14 all four
    candidates it offered were exactly that — `nfl-2024-02-24-track4s58-28.gpx` is fix
    `6755398652971554`, `nfl-2024-03-03-track4s69-112.gpx` is fix `6755398652971558` — so
    acting on the list would have put a second copy of that water on the journey.

    The tracker's chord being still present is not evidence that the repair is outstanding:
    the fill went up and **the chord was never removed**, which is a subtraction still owed,
    not an addition.

    Weighted by distance rather than by edge count, so one long uncovered stretch outweighs
    several short covered ones — otherwise a slice that is mostly missing reads as mostly
    present.
    """
    if len(sl) < 2 or not lines:
        return 0.0
    idx = FG.Index(lines)
    covered = total = 0.0
    for i in range(len(sl)-1):
        step = FG.hav(sl[i], sl[i+1])
        total += step
        mid = ((sl[i][0]+sl[i+1][0])/2, (sl[i][1]+sl[i+1][1])/2)
        if idx.distance(mid[0], mid[1], stop_at=tol_m) <= tol_m:
            covered += step
    return 100.0*covered/total if total else 0.0

def _deviation(sl, a, b):
    """max and mean perpendicular distance in metres from the chord a->b."""
    R = 6371000.0
    def xy(la, lo, la0):
        p = math.pi/180
        return (lo*p*R*math.cos(la0*p), la*p*R)
    ds = []
    for q in sl:
        la0 = q[0]
        px, py = xy(q[0], q[1], la0)
        ax, ay = xy(a[0], a[1], la0); bx, by = xy(b[0], b[1], la0)
        dx, dy = bx-ax, by-ay
        if dx == 0 and dy == 0:
            ds.append(math.hypot(px-ax, py-ay)); continue
        t = ((px-ax)*dx + (py-ay)*dy)/(dx*dx+dy*dy)
        ds.append(math.hypot(px-(ax+t*dx), py-(ay+t*dy)))
    return (max(ds), sum(ds)/len(ds)) if ds else (0.0, 0.0)

def covering_slice(segs, a, b):
    """Best plotter slice spanning chord a->b: (file, track, si, points, direction)."""
    best = None
    for fn, name, si, p in segs:
        ia = min(range(len(p)), key=lambda i: FG.hav(p[i], a))
        ib = min(range(len(p)), key=lambda i: FG.hav(p[i], b))
        da, db = FG.hav(p[ia], a), FG.hav(p[ib], b)
        if max(da, db) > 1.0:            # both ends must actually be on this segment
            continue
        lo, hi = min(ia, ib), max(ia, ib)
        if hi-lo < MIN_SLICE_POINTS - 1:
            continue
        sl = p[lo:hi+1]
        if ia > ib:
            sl = sl[::-1]
        nm = sum(FG.hav(sl[i], sl[i+1]) for i in range(len(sl)-1))
        score = max(da, db)
        if best is None or score < best[0]:
            best = (score, fn, name, si, sl, nm)
    return best

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--from', dest='lo', default='2023-01-01')
    ap.add_argument('--to', dest='hi', default='2024-12-31')
    ap.add_argument('--min-chord', type=float, default=MIN_JUMP_NM,
                    help='nm; a vertex-to-vertex jump at least this long counts as missing '
                         'data worth replacing (default 1.0)')
    ap.add_argument('--cache', default='/tmp/j3.json')
    ap.add_argument('--list', action='store_true', help='report candidates and stop')
    ap.add_argument('--rank', type=int, default=None,
                    help='fix the Nth candidate (1 = largest with usable times)')
    ap.add_argument('--all', action='store_true', help='build every usable candidate')
    ap.add_argument('--outbox', default='/tmp/outbox_chords')
    ap.add_argument('--tolerance', type=float, default=300.0,
                    help='metres; how close an existing journey line counts as holding the '
                         'slice already')
    ap.add_argument('--covered-threshold', type=float, default=70.0,
                    help='%% of the slice already on the journey above which the repair is '
                         'treated as done - sending it again would duplicate it')
    a = ap.parse_args()
    d = FG.fetch(a.cache)
    ch, segs = chords(d, a.lo, a.hi, a.min_chord, TRACKS_2023_24)
    usable, done = [], []
    for step, t, i, va, vb, hits, fid in ch:
        if not va[2] or not vb[2]:
            continue                      # epoch 0: no time to interpolate between
        if hits < 8:
            continue                      # plotter must cover essentially the whole chord
        ta = datetime.fromtimestamp(va[2]/1000, UTC)
        tb = datetime.fromtimestamp(vb[2]/1000, UTC)
        hrs = (tb-ta).total_seconds()/3600
        if not (0.2 < hrs < 48):
            continue
        kn = step/hrs
        if not (0.5 <= kn <= 12):
            continue
        got = covering_slice(segs, va, vb)
        if not got:
            continue
        _, fn, name, si, sl, snm = got
        dev_max, dev_mean = _deviation(sl, va, vb)
        gaps = [FG.hav(sl[i], sl[i+1])*1852 for i in range(len(sl)-1)]
        spacing = sorted(gaps)[len(gaps)//2] if gaps else 0.0
        # Is this plotter cover already uploaded? A chord still being present is not evidence
        # that the repair is outstanding - the fill may have gone up and the chord never been
        # removed, which is a subtraction owed rather than an addition.
        pct = already_on_journey(sl, journey_lines_except(d, fid), a.tolerance)
        row = (step, t, va, vb, ta, tb, kn, dev_max, spacing, len(sl),
               f'{name} s{si}', pct, fid)
        (done if pct >= a.covered_threshold else usable).append(row)
    # rank by the size of the gap being closed. This was `-r[7]`, the deviation, until
    # 2026-08-14: the owner's rule is that a jump over a nautical mile is missing data and
    # an 11 m deviation is GPS noise, so the gap is what decides and the deviation is only
    # reported.
    usable.sort(key=lambda r: -r[0])
    print(f'{len(ch)} chords over {a.min_chord} nm; {len(usable)} have plotter cover, real '
          f'times at both ends and a locatable slice\n')
    if done:
        print(f'** {len(done)} more are ALREADY ON THE JOURNEY and are excluded — the plotter '
              f'fill went up previously and the tracker chord was never removed.')
        print('   Those need the chord deleting, not the track sending again. '
              '`find_backtracks.py --windows` shows them as nesting.')
        for r in done:
            print(f'   {r[10]:14s} {r[4].strftime("%Y-%m-%d %H:%M")} .. '
                  f'{r[5].strftime("%H:%M")}  {r[0]:5.2f} nm  {r[11]:3.0f}% already held  '
                  f'tracker fix {r[12]}')
        print()
    print(f'{"#":>3s} {"nm":>6s} {"OFF BY":>8s} {"spacing":>8s} {"pts":>5s} '
          f'{"window (UTC)":31s} {"kn":>5s}  track')
    for n, r in enumerate(usable, 1):
        step, t, va, vb, ta, tb, kn, dev, sp, npts, who, pct, fid = r
        print(f'{n:3d} {step:6.2f} {dev:7.0f}m {sp:7.0f}m {npts:5d} '
              f'{ta.strftime("%Y-%m-%d %H:%M")} .. {tb.strftime("%Y-%m-%d %H:%M")} '
              f'{kn:5.1f}  {who}')
    big = [r for r in usable if r[0] >= 5.0]
    print(f'\nall {len(usable)} are worth replacing; {len(big)} close a gap of 5 nm or more '
          f'and are the ones to do first')
    if a.list or (a.rank is None and not a.all):
        return
    picks = list(range(len(usable))) if a.all else [a.rank-1]
    built = 0
    for k in picks:
        if _emit(usable[k], k+1, segs, a.outbox):
            built += 1
    print(f'\n{built} of {len(picks)} built into {a.outbox}')

def _emit(row, rank, segs, outbox):
    step, t, va, vb, ta, tb, kn, dev, sp, npts, who, pct, fid = row
    got = covering_slice(segs, va, vb)
    if not got:
        print(f'{rank:3d} no single plotter segment spans that chord')
        return False
    score, fn, name, si, sl, nm = got
    # The chord's far end may be the parent line's own last vertex, i.e. the tracker fix
    # itself. A new fix within a few metres of an existing one is merged silently, so trim
    # the slice back until its end is clear of that position.
    trimmed = 0
    while len(sl) > 12 and FG.hav(sl[-1], vb)*1852 < 80:
        sl.pop(); trimmed += 1
    if trimmed:
        nm = sum(FG.hav(sl[i], sl[i+1]) for i in range(len(sl)-1))
        frac = nm/step if step else 1.0
        tb = ta + (tb-ta)*min(1.0, frac)
    print(f'\ncovering plotter track: {fn} {name} s{si}')
    print(f'  slice {len(sl)} points, {nm:.2f} nm against a {step:.2f} nm chord '
          f'(ends matched within {score*1852:.0f} m)')
    label = f'{ta.strftime("%Y-%m-%d")} {nm:.1f} nm recorded by the chartplotter'
    desc = (f'Chartplotter geometry replacing a {step:.2f} nm straight line in the journey. '
            f'The on-board GPS/GSM tracker stopped recording here - it depends on cellphone '
            f'coverage - so this stretch was drawn as a chord between two tracker vertices. '
            f'The plotter did record it: {nm:.2f} nm of track against the {step:.2f} nm '
            f'straight line. The times are the tracker\'s own, taken from the vertices at '
            f'each end of the chord ({ta.strftime("%H:%M")} and {tb.strftime("%H:%M")} UTC), '
            f'so position comes from the plotter and timing from the tracker. '
            f'{nm/((tb-ta).total_seconds()/3600):.1f} kn.')
    fname = (f"nfl-{ta.strftime('%Y-%m-%d')}-chord-"
             f"{name.replace(' ', '').lower()}s{si}-{ta.strftime('%H%M')}.gpx")
    r = LE.build(sl, label, desc, ta, tb, fname, creator=CREATOR, min_spacing_m=0,
                 outbox=outbox)
    print(f'{rank:3d} {r[0]:6.2f} nm {r[1]:3d} pts {r[2]:4.1f} kn  off by {dev:5.0f}m  '
          f'{fname}{"  (trimmed " + str(trimmed) + ")" if trimmed else ""}')
    return True

if __name__ == '__main__':
    main()
