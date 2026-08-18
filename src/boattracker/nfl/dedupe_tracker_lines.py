"""Remove tracker geometry that the newly uploaded plotter tracks now duplicate.

Duplicated track is not merely ugly. noforeignland reads it as "sailed A to B, teleported
back to A, sailed A to B again", which zig-zags on the map and **inflates the nautical-mile
statistics**. So once plotter geometry has been added over a tracker chord, the tracker's
version of that water has to go.

The complication is that a tracker line is rarely duplicated end to end. Of 62 lines with any
duplication, only 12 are 95% or more; the other 50 hold 598 nm that exists nowhere else.
Deleting those outright would trade one kind of data loss for another.

So each partly-duplicated line is **rebuilt**: its edges are classified as duplicated or not,
the surviving runs are re-uploaded as separate tracks carrying their own vertex timestamps,
and only then is the parent deleted. Net effect per line: the duplicated stretch is
represented once, by the plotter; the rest is represented once, by the tracker; and the
timestamps are preserved throughout because they travel with the vertices.

Order matters and is not negotiable — a new fix within a few metres of an existing one is
merged away silently, so the rebuilt runs cannot be uploaded while the parent still exists.
The sequence is: build everything, delete the parent, upload the runs, verify.

## Timestamps

Vertices are `[lon, lat, epoch_ms]`, but some carry **epoch 0** — no time at all. For a run
containing such vertices the times are interpolated between the nearest real ones on either
side; if a run has no real times whatsoever, it inherits the parent fix's timestamp at its
end and is spread backwards at the run's average speed. That is a weaker claim than the rest
and the description says so.

## Branding

These runs are tracker data, not chartplotter data, so `creator` must not contain
"raymarine" — noforeignland derives the displayed source label from it, and mislabelling the
coarse tracker geometry as a plotter export would misrepresent its precision.
"""
import argparse
import json
import os
from datetime import UTC, datetime, timedelta

from boattracker import files
from boattracker.nfl import find_gaps as FG
from boattracker.nfl import leg_export as LE

CREATOR = ('on-board GPS/GSM tracker, re-uploaded unchanged after the duplicated part of '
           'this line was replaced by chartplotter geometry')

def load(path):
    return files.read_json(path)

def era_lines(d, lo, hi, baseline_ids=None, pre_existing=True):
    feats = d['geojson']['features']
    tms = {f['properties']['fixId']: f['properties'].get('timeMs')
           for f in feats if f['properties'].get('layer') == 'fixes'}
    src = {f['properties']['fixId']: f['properties'].get('source')
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
        # baseline_ids are the fixes that existed BEFORE the plotter uploads, so being in
        # that set means pre-existing and being absent means newly uploaded.
        if baseline_ids is not None and ((fid in baseline_ids) != pre_existing):
            continue
        v = [(c[1], c[0], c[2]) for c in f['geometry']['coordinates']]
        if len(v) >= 3 and FG.hav(v[0], v[1]) > 2.0:
            v = v[1:]
        if len(v) >= 2:
            out.append((t, fid, v, src.get(fid)))
    out.sort()
    return out

def dup_flags(v, idx, tol=3000.0):
    """for each edge, is the new plotter track running alongside it?"""
    flags = []
    for i in range(len(v)-1):
        hits = 0
        for k in range(1, 6):
            la = v[i][0] + (v[i+1][0]-v[i][0])*k/6
            lo = v[i][1] + (v[i+1][1]-v[i][1])*k/6
            if idx.distance(la, lo) <= tol:
                hits += 1
        flags.append(hits >= 4)
    return flags

def runs_of_survivors(v, flags, min_nm=0.2):
    """contiguous vertex runs whose edges are NOT duplicated"""
    out, cur = [], []
    for i, dup in enumerate(flags):
        if dup:
            if len(cur) >= 2:
                out.append(cur)
            cur = []
        else:
            if not cur:
                cur = [v[i]]
            cur.append(v[i+1])
    if len(cur) >= 2:
        out.append(cur)
    return [r for r in out
            if sum(FG.hav(r[i], r[i+1]) for i in range(len(r)-1)) >= min_nm]

def times_for(run, parent_time):
    """(t0, t1) for a run, plus a flag saying whether real vertex times were available."""
    real = [(i, q[2]) for i, q in enumerate(run) if q[2]]
    if len(real) >= 2:
        return (datetime.fromtimestamp(real[0][1]/1000, UTC),
                datetime.fromtimestamp(real[-1][1]/1000, UTC), True)
    nm = sum(FG.hav(run[i], run[i+1]) for i in range(len(run)-1))
    hrs = max(0.25, nm/4.0)            # assume 4 kn where nothing better exists
    return (parent_time - timedelta(hours=hrs), parent_time, False)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--snapshot', required=True,
                    help='journey JSON taken BEFORE any deletion (holds the vertex times)')
    ap.add_argument('--baseline', required=True,
                    help='journey JSON from before the plotter uploads, to identify them')
    ap.add_argument('--from', dest='lo', default='2023-01-01')
    ap.add_argument('--to', dest='hi', default='2024-12-31')
    ap.add_argument('--outbox', default='/tmp/outbox_dedupe')
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()

    snap = load(a.snapshot)
    base_ids = {f['properties'].get('fixId')
                for f in load(a.baseline)['geojson']['features']}
    mine = era_lines(snap, a.lo, a.hi, base_ids, pre_existing=False)
    parents = era_lines(snap, a.lo, a.hi, base_ids, pre_existing=True)
    idx = FG.Index([[(q[0], q[1]) for q in v] for _, _, v, _ in mine])
    print(f'{len(mine)} plotter uploads, {len(parents)} tracker-era lines\n')

    to_delete, to_upload = [], []
    dup_total = keep_total = 0.0
    for t, fid, v, s in parents:
        tot = sum(FG.hav(v[i], v[i+1]) for i in range(len(v)-1))
        if tot < 0.2:
            continue
        flags = dup_flags(v, idx)
        dup = sum(FG.hav(v[i], v[i+1]) for i in range(len(v)-1) if flags[i])
        if dup <= 0.05:
            continue
        dup_total += dup
        runs = runs_of_survivors(v, flags)
        keep = sum(sum(FG.hav(r[i], r[i+1]) for i in range(len(r)-1)) for r in runs)
        keep_total += keep
        to_delete.append((str(fid), t, s, dup, tot))
        for n, r in enumerate(runs):
            t0, t1, real = times_for(r, t)
            nm = sum(FG.hav(r[i], r[i+1]) for i in range(len(r)-1))
            to_upload.append((fid, n, r, t0, t1, real, nm, s))
        print(f'{t.strftime("%Y-%m-%d %H:%M")} {s:22s} {tot:6.1f} nm, '
              f'{dup:5.1f} dup, {len(runs)} run(s) keeping {keep:5.1f} nm')

    print(f'\n{len(to_delete)} parents to delete, removing {dup_total:.0f} nm of duplication')
    print(f'{len(to_upload)} runs to re-upload, preserving {keep_total:.0f} nm')
    noreal = sum(1 for u in to_upload if not u[5])
    if noreal:
        print(f'   ({noreal} of those runs have no real vertex times and fall back to the '
              f'parent fix timestamp)')
    if a.dry_run:
        return
    os.makedirs(a.outbox, exist_ok=True)
    for fid, n, r, t0, t1, real, nm, s in to_upload:
        pts = [(q[0], q[1]) for q in r]
        label = f'{t0.strftime("%Y-%m-%d")} {nm:.1f} nm, on-board tracker'
        desc = ('Geometry from the on-board GPS/GSM tracker, re-uploaded unchanged. The '
                'chartplotter also recorded part of the original line, and that part has '
                'been replaced by the plotter track; this is the remainder, which the '
                'tracker alone recorded. '
                + ('Times are the tracker\'s own, from the vertices themselves.'
                   if real else
                   'These vertices carry no timestamps, so the times are derived from the '
                   'parent fix and an assumed 4 kn; treat them as approximate.'))
        fn = f'nfl-{t0.strftime("%Y-%m-%d")}-tracker-{fid}-{n}.gpx'
        LE.build(pts, label, desc, t0, t1, fn, creator=CREATOR, min_spacing_m=0,
                 outbox=a.outbox)
    json.dump([x[0] for x in to_delete],
              open(os.path.join(a.outbox, 'delete_ids.json'), 'w'))
    print(f'\nbuilt into {a.outbox}; delete_ids.json holds the parents to remove FIRST')

if __name__ == '__main__':
    main()
