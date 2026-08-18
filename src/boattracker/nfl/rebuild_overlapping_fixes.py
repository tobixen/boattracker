"""Clear the residual overlap in hand-placed fixes by rebuilding them.

`prune_superseded_fixes.py` deletes a `Check in` / `Manual` / `NFL App` fix only when track
data covers it *entirely*. That leaves the partly-overlapped ones in place, and with them
about 20 nm of geometry drawn twice — enough to keep inflating the mileage statistic. This
finishes the job: delete each partly-overlapped fix and re-upload only the parts of its line
that nothing else holds.

## Who keeps the shared water

Overlap has to be resolved in favour of exactly one holder, or deleting both sides of a pair
would lose the water altogether. Two rules, applied greedily in time order:

1. **Real track sources always win.** `GPX Export` (the on-board tracker) and
   `Raymarine GPX Export` (the chartplotter) are seeded into the index as authoritative
   before anything is considered, so a hand-placed line never displaces recorded track.
2. **Among hand-placed fixes, the earliest wins.** Each fix's surviving runs are added to the
   index as it is processed, so a later app line overlapping an earlier one drops the shared
   part rather than duplicating it. This is what stops the `NFL App` + `NFL App` pairs from
   cancelling each other out.

## The importer rejects colliding timestamps — and says so

Two distinct failure modes, and they behave differently:

* **Position merge** — a new fix within a few metres of an existing one is absorbed
  *silently*, with no error at all. This is what swallowed two of the March 2025 legs.
* **Timestamp collision** — a GPX whose track timestamp matches one already on the journey is
  **refused with an error**: "A GPX track with the same timestamp was already found on your
  boat journey ... you must first delete the current one."

The first version of this script walked into the second one: every run of a multi-run parent
was given the parent fix's own timestamp as its end, so the second run of each of five
parents was refused. That was also simply wrong on its own terms — the runs are ordered along
the original line, so run 0 must end *before* run 1 begins. Each parent's window is now
divided between its runs in proportion to distance.

## A consequence worth stating plainly

Re-uploading is done by GPX, and the importer derives the source label from the `creator`
attribute — there is no way to recreate the `NFL App` or `Check in` label. So a rebuilt fix
will no longer be badged as an app fix. The geometry, position and times are preserved
exactly; the provenance survives only in the `creator` string and the description, which say
where it came from. That is a real loss of a searchable label, and the reason this is worth
doing only when the mileage figure needs to be exact.
"""
import argparse
import os
from datetime import UTC, datetime

from boattracker import files
from boattracker.nfl import find_gaps as FG
from boattracker.nfl import leg_export as LE
from boattracker.nfl.dedupe_tracker_lines import runs_of_survivors
from boattracker.nfl.prune_superseded_fixes import HAND, TRACK, collect

CREATOR = ('noforeignland app and check-in geometry, re-uploaded after the parts duplicated '
           'by other track data were removed - not chartplotter data')

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--snapshot', required=True)
    ap.add_argument('--from', dest='lo', default='2023-01-01')
    ap.add_argument('--to', dest='hi', default='2024-12-31')
    ap.add_argument('--tolerance', type=float, default=200.0)
    ap.add_argument('--window-hours', type=float, default=36.0)
    ap.add_argument('--only', default=None,
                    help='comma-separated parent fixIds to rebuild (default: all)')
    ap.add_argument('--outbox', default='/tmp/outbox_rebuild')
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    fixes = collect(files.read_json(a.snapshot))
    win = a.window_hours*3600

    def in_window(v):
        t = datetime.fromtimestamp(v['t'], UTC)
        return a.lo <= t.strftime('%Y-%m-%d') <= a.hi

    # authoritative geometry: everything from a real track source
    kept = []
    for fid, v in fixes.items():
        if v['src'] in TRACK and len(v['line']) >= 2:
            kept.append((v['line'], v['t']))
    hand = sorted([(fid, v) for fid, v in fixes.items()
                   if v['src'] in HAND and in_window(v) and len(v['line']) >= 2],
                  key=lambda kv: kv[1]['t'])
    print(f'{len(kept)} authoritative track lines seeded; {len(hand)} hand-placed lines '
          f'in {a.lo}..{a.hi}\n')

    def dup_edge(p, q, ts):
        near = [w for w, wt in kept if abs(wt-ts) <= win]
        if not near:
            return False
        idx = FG.Index(near)
        mid = ((p[0]+q[0])/2, (p[1]+q[1])/2)
        return idx.distance(*mid) <= a.tolerance

    to_delete, to_upload = [], []
    dup_total = keep_total = 0.0
    for fid, v in hand:
        t = datetime.fromtimestamp(v['t'], UTC)
        w = v['line']
        flags = [dup_edge(w[i], w[i+1], v['t']) for i in range(len(w)-1)]
        dup = sum(FG.hav(w[i], w[i+1]) for i in range(len(w)-1) if flags[i])
        tot = sum(FG.hav(w[i], w[i+1]) for i in range(len(w)-1))
        if dup < 0.3:
            # nothing meaningful duplicated: leave it alone, and let it hold its water
            kept.append((w, v['t']))
            continue
        runs = runs_of_survivors([(p[0], p[1], 0) for p in w], flags)
        keep_nm = sum(sum(FG.hav(r[i], r[i+1]) for i in range(len(r)-1)) for r in runs)
        dup_total += dup; keep_total += keep_nm
        to_delete.append(str(fid))
        for n, r in enumerate(runs):
            to_upload.append((fid, n, r, v, t))
            kept.append(([(q[0], q[1]) for q in r], v['t']))
        print(f'{t.strftime("%Y-%m-%d %H:%M")} {v["src"]:9s} {tot:6.2f} nm, '
              f'{dup:5.2f} duplicated, {len(runs)} run(s) keeping {keep_nm:5.2f} nm')

    print(f'\n{len(to_delete)} fixes to rebuild, removing {dup_total:.1f} nm of duplication')
    print(f'{len(to_upload)} runs to re-upload, preserving {keep_total:.1f} nm')
    if a.dry_run:
        return
    os.makedirs(a.outbox, exist_ok=True)
    only = set(a.only.split(',')) if a.only else None
    # group by parent so each parent's window can be split between its runs in order
    from collections import defaultdict
    from datetime import timedelta
    grouped = defaultdict(list)
    for item in to_upload:
        grouped[item[0]].append(item)
    for pfid, items in grouped.items():
        if only and str(pfid) not in only:
            continue
        items.sort(key=lambda x: x[1])
        dists = [sum(FG.hav(it[2][i], it[2][i+1]) for i in range(len(it[2])-1))
                 for it in items]
        total = sum(dists) or 1.0
        t_end = items[0][4]
        span_h = max(0.25, total/4.0)          # assumed 4 kn, nothing better exists
        t_start = t_end - timedelta(hours=span_h)
        acc = 0.0
        for (fid, n, r, v, t), dist in zip(items, dists):
            t0 = t_start + timedelta(hours=span_h*acc/total)
            acc += dist
            t1 = t_start + timedelta(hours=span_h*acc/total)
            _write(fid, n, r, v, t0, t1, dist, a.outbox)
    files.write_json(os.path.join(a.outbox, 'delete_ids.json'), to_delete)
    print(f'\nbuilt into {a.outbox}; delete_ids.json must be applied FIRST')

def _write(fid, n, r, v, t0, t, nm, outbox):
    pts = [(q[0], q[1]) for q in r]
    if True:
        label = f'{t.strftime("%Y-%m-%d")} {nm:.1f} nm, originally a {v["src"]} fix'
        desc = (f'Geometry that arrived on the journey as a "{v["src"]}" fix, re-uploaded '
                f'after the part of it duplicated by other track data was removed. '
                f'Duplicated track is read as sailing a leg, teleporting back and sailing '
                f'it again, which inflates the mileage statistic. The original fix carried '
                f'no per-vertex times, so the window is derived from its own timestamp at '
                f'an assumed 4 kn; the positions are unchanged. This is not chartplotter '
                f'data and is coarser than a plotter track.')
        fn = f'nfl-{t.strftime("%Y-%m-%d")}-rebuilt-{fid}-{n}.gpx'
        LE.build(pts, label, desc, t0, t, fn, creator=CREATOR, min_spacing_m=0,
                 outbox=outbox)
        print(f'   run {n} of {fid}: {nm:.2f} nm, '
              f'{t0.strftime("%H:%M:%S")}-{t.strftime("%H:%M:%S")}')

if __name__ == '__main__':
    main()
