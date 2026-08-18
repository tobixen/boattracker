"""Export the stretches of plotter track that the journey is missing inside a segment.

The gap scans that came before this asked "is this segment on the journey?" and so missed the
commonest case entirely: a segment that is mostly present, absent only where the tracker had
dropped out. `Track 4` s95 is 78% present, and the 17% missing is precisely the water where the
journey instead draws a 15 nm chord across the peninsula outside Marmaris. Whole-segment tests
declared 2024 clean while that was on the map.

## Dating, without guessing

A missing run usually has *covered* track on one or both sides of it, and covered track lies on
a journey line whose vertices each carry their own `epoch_ms`. So the run can be bracketed by
reading the timestamps of the journey vertices nearest its two ends — the plotter supplies the
geometry, the journey supplies the clock, and no diary interpretation is needed.

Where only one side is covered, that side gives one bound and the other is derived from the
run's length at an assumed 4 kn. Where neither is (a wholly-missing segment), this script skips
it: those belong in a per-day export where the diary can date them properly.

Which of the nearby vertices to take matters as much as the window. Picking the spatially
closest one is wrong: at a place the boat visits repeatedly there are several within tolerance,
from different days. For the run's *start* take the **latest** vertex within tolerance and for
its *end* the **earliest**, which gives the tightest bracket consistent with the run sitting
between them. Taking the nearest instead put the Marmaris departure between 04-05 and 04-23 —
eighteen days for 13 nm — and the implausible speed then rejected the very run being chased.

The bracketing vertex must be looked for **within the segment's own date window**. Searching
the whole year picks the spatially nearest vertex regardless of when it was recorded, and in
water the boat revisits — Marmaris above all — that can be months away, which made the implied
speed absurd and caused the very run being chased to be rejected.

Runs are timestamped strictly inside their bracket, offset a little from the boundary, so they
cannot collide with the timestamp of an existing track — the importer refuses a GPX whose track
timestamp already exists.
"""
import argparse
from datetime import UTC, datetime, timedelta

from boattracker import files
from boattracker.nfl import find_gaps as FG
from boattracker.nfl import leg_export as LE
from boattracker.nfl import track_dates as TD

CREATOR = ('raymarine track, positioned by the chartplotter and timed from the surrounding '
           'journey fixes')

def timed_vertices(d, lo, hi):
    """[(lat, lon, epoch_ms)] for every journey vertex in the window that carries a time."""
    feats = d['geojson']['features']
    tms = {f['properties']['fixId']: f['properties'].get('timeMs')
           for f in feats if f['properties'].get('layer') == 'fixes'}
    out = []
    for f in feats:
        if f['geometry']['type'] != 'LineString':
            continue
        fid = f['properties'].get('fixId')
        ms = tms.get(fid)
        if not ms:
            continue
        t = datetime.fromtimestamp(ms/1000, UTC)
        if not (lo <= t.strftime('%Y-%m-%d') <= hi):
            continue
        v = f['geometry']['coordinates']
        for i, c in enumerate(v):
            stamp = c[2] if len(c) > 2 and c[2] else ms
            # skip the leading connector vertex: it is drawing order, not recorded track
            if i == 0 and len(v) >= 3 and FG.hav((c[1], c[0]), (v[1][1], v[1][0])) > 2.0:
                continue
            out.append((c[1], c[0], stamp/1000.0))
    return out

def bracket_time(pt, verts, win, side, max_nm=0.5):
    """Timestamp bounding a run at `pt`.

    `side` is 'before' or 'after'. Among the timed vertices within `max_nm` and inside the
    segment's window, take the latest for 'before' and the earliest for 'after' — the tightest
    bracket rather than the spatially nearest, which at a revisited place can be weeks off.
    """
    lo = datetime(win[0].year, win[0].month, win[0].day, tzinfo=UTC).timestamp()
    hi = datetime(win[1].year, win[1].month, win[1].day, tzinfo=UTC).timestamp()+86400
    cands = [ts for la, lo_, ts in verts
             if lo <= ts <= hi and FG.hav((la, lo_), pt) <= max_nm]
    if not cands:
        return None, 9e9
    return (max(cands) if side == 'before' else min(cands)), 0.0

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--cache', required=True)
    ap.add_argument('--from', dest='lo', required=True)
    ap.add_argument('--to', dest='hi', required=True)
    ap.add_argument('--tracks', required=True)
    ap.add_argument('--min-nm', type=float, default=1.0)
    ap.add_argument('--tolerance', type=float, default=300.0)
    ap.add_argument('--outbox', default='/tmp/outbox_partial')
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    d = files.read_json(a.cache)
    tracks = {x.strip() for x in a.tracks.split(',')}
    pool = FG.journey_lines(d, '2000-01-01', '2100-01-01')
    buckets = {}
    for t, v in pool:
        buckets.setdefault(t.strftime('%Y-%m'), []).append(v)
    verts = timed_vertices(d, a.lo, a.hi)
    print(f'{len(verts)} timed journey vertices in {a.lo}..{a.hi}')
    segs = FG.source_segments(tracks=tracks, min_excursion=0.0, min_points=2)
    seen, built, skipped = set(), 0, []
    print(f'\n{"segment":18s} {"nm":>6s} {"window (UTC)":33s} {"kn":>5s}  status')
    for fn, name, si, p in segs:
        if (name, si) in seen:
            continue
        seen.add((name, si))
        win = TD.segment_window(name, si)
        if win is None:
            continue
        keys, y, m = [], win[0].year, win[0].month
        while (y, m) <= (win[1].year, win[1].month):
            keys.append(f'{y:04d}-{m:02d}')
            m += 1
            if m > 12:
                y, m = y+1, 1
        idx = FG.Index([v for k in keys for v in buckets.get(k, ())])
        for A, B, nm in FG.uncovered_runs(p, idx, a.tolerance, a.min_nm):
            run = p[A:B+1]
            t_before, _ = bracket_time(p[max(0, A-1)], verts, win, 'before')
            t_after, _ = bracket_time(p[min(len(p)-1, B+1)], verts, win, 'after')
            if t_before is not None and t_after is not None and t_after <= t_before:
                t_after = None      # inconsistent bracket: fall back to one side
            if t_before is None and t_after is None:
                skipped.append((name, si, nm, 'no timed journey vertex either side'))
                continue
            hrs = max(0.3, nm/4.0)
            if t_before is not None and t_after is not None:
                t0 = datetime.fromtimestamp(t_before, UTC)+timedelta(minutes=2)
                t1 = datetime.fromtimestamp(t_after, UTC)-timedelta(minutes=2)
                if t1 <= t0:
                    t1 = t0+timedelta(hours=hrs)
            elif t_before is not None:
                t0 = datetime.fromtimestamp(t_before, UTC)+timedelta(minutes=2)
                t1 = t0+timedelta(hours=hrs)
            else:
                t1 = datetime.fromtimestamp(t_after, UTC)-timedelta(minutes=2)
                t0 = t1-timedelta(hours=hrs)
            kn = nm/((t1-t0).total_seconds()/3600)
            if not (0.3 <= kn <= 10.0):
                skipped.append((name, si, nm, f'implied {kn:.1f} kn, refusing'))
                continue
            label = f'{t0.strftime("%Y-%m-%d")} {nm:.1f} nm not previously on the journey'
            desc = (f'Chartplotter geometry for a stretch the journey did not hold. The '
                    f'on-board tracker had dropped out here, so the journey drew a straight '
                    f'line across it; this is what the plotter recorded, {nm:.2f} nm of it. '
                    f'The times are read from the journey\'s own vertices immediately either '
                    f'side of the missing stretch, so position comes from the plotter and '
                    f'timing from the existing track. {kn:.1f} kn. Positions from a Raymarine '
                    f'chartplotter, which records no time information in its GPX exports.')
            slug = name.replace(' ', '').replace('.', '_').lower()
            fname = f'nfl-{t0.strftime("%Y-%m-%d")}-{slug}s{si}-{A}.gpx'
            print(f'{name+" s"+str(si):18s} {nm:6.2f} {t0.strftime("%m-%d %H:%M")}..'
                  f'{t1.strftime("%m-%d %H:%M")}                 {kn:5.1f}  build')
            if not a.dry_run:
                LE.build(run, label, desc, t0, t1, fname, creator=CREATOR,
                         min_spacing_m=0, outbox=a.outbox)
            built += 1
    print(f'\n{built} runs built')
    if skipped:
        print(f'{len(skipped)} skipped:')
        for name, si, nm, why in skipped:
            print(f'   {name} s{si}: {nm:.2f} nm - {why}')
    if not a.dry_run:
        print(f'outbox {a.outbox}')

if __name__ == '__main__':
    main()
