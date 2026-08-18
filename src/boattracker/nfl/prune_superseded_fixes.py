"""Delete check-ins, manual points and app fixes that real track data has superseded.

**Read the precedence rule in `../SOURCES.md` first.** It is the owner's, dated 2026-08-12,
and it is what this script implements: the Raymarine plotter carries the best positions, the
on-board tracker the best timestamps, and where both exist almost everything else can come
off the site. The three sources here are *not* equivalent under that rule —

* `Check in` — **never an accurate position**, and the timestamp is not trustworthy either.
  Remove wherever better data exists. The time may still be used when there is nothing else.
* `Manual` — usually an exact position and time, but **where it sits decides its fate, and
  this script cannot tell the two apart.** A one-point fix *in the middle of* a track must go
  — the renderer runs to it and back out, manufacturing a backtrack — while one *between* two
  tracks, at a harbour or anchorage, should be kept, because it carries a **departure** time
  and every fix timestamp is otherwise an arrival. The coverage test here sees only "track
  passes near this point", which is true of both. So read the `Manual` rows before acting on
  them; `../IMPROVE-TRACKS.md` has the rule.
* `NFL App` — generally quite reliable, just less so than the other two, and its weakness is
  **coverage rather than precision**: the app is not reliably started when the boat leaves
  nor stopped when she arrives, so a passage is often only partly recorded and it sometimes
  keeps running ashore, drawing a car or train journey as a passage. Replace it where real
  track exists; its lines carry timestamps, which can date Raymarine geometry over the same
  water.

**Nothing here is thrown away — it comes off the site and stays on disk.** Export the fixes
this lists with `reimport_journey.py` into `../nfl-retired/` and verify the GPX *before*
deleting anything. A snapshot preserves the geometry but cannot be re-uploaded; the GPX can.
For `NFL App` lines the owner asked for this explicitly: their geometry, including any points
routed by hand on the map, exists nowhere else.

Hand-placed fixes were the only evidence for many days before the plotter exports were
recovered. Most of those days now have real track, and the hand-placed points have gone from
being the record to being duplication — which noforeignland reads as "sailed A to B,
teleported back to A, sailed A to B again", inflating the mileage statistic and zig-zagging
the map.

The rule this implements: **a `Check in`, `Manual` or `NFL App` fix is deleted once track
data covers it.** Nothing else. A hand-placed point with no track near it in time is still
the only record of its day and is kept.

## What counts as superseded

* The covering line must belong to a **different fix** and come from a real track source —
  `GPX Export` (the on-board GPS/GSM tracker) or `Raymarine GPX Export` (the chartplotter).
  One manual point does not supersede another.
* The covering line must be near in **time as well as position**. The boat returns to the
  same anchorages for years; a 2025 track passing a 2023 check-in supersedes nothing.
* Fixes carrying their own geometry — some `NFL App` fixes hold real tracks, one of 33 nm —
  are judged on how much of that **line** is duplicated, not just their end point. Below the
  threshold they are kept, because they would be carrying track nothing else has.

## Leading connectors

Each rendered line starts at the previous fix's position, so that first edge is an artefact
of drawing order rather than recorded track. It is stripped before anything is measured;
left in, it would make a hand-placed point look covered by the very line drawn to reach it.
"""
import argparse
import json
import math
from datetime import UTC, datetime

from boattracker import files
from boattracker.nfl import find_gaps as FG

HAND = {'Check in', 'Manual', 'NFL App'}
TRACK = {'GPX Export', 'Raymarine GPX Export'}
# A check-in's position is not evidence, so the distance from it to real track is not
# evidence either — see the precedence rule in `../SOURCES.md`. What the coverage test can
# still ask of a check-in is whether real track exists *around that time at all*, so it is
# judged on a deliberately loose radius. 5 km is a judgement, not a measurement: wide enough
# that an app-placed or tapped position cannot survive by being wrong, tight enough that
# track from a different harbour on the same day does not count. `--checkin-tolerance` moves
# it. `Manual` and `NFL App` positions mean what they say and keep the ordinary tolerance.
CHECKIN_TOLERANCE = 5000.0

def tolerance_for(src, base, checkin=None):
    """Metres within which this source counts as covered by real track."""
    if src == 'Check in':
        return max(base, CHECKIN_TOLERANCE if checkin is None else checkin)
    return base
R = 6371000.0

def _xy(la, lo, la0):
    p = math.pi/180
    return (lo*p*R*math.cos(la0*p), la*p*R)

def _sd(px, py, ax, ay, bx, by):
    dx, dy = bx-ax, by-ay
    if dx == 0 and dy == 0:
        return math.hypot(px-ax, py-ay)
    t = max(0.0, min(1.0, ((px-ax)*dx + (py-ay)*dy)/(dx*dx+dy*dy)))
    return math.hypot(px-(ax+t*dx), py-(ay+t*dy))

class TimedIndex:
    """point -> nearest track edge, restricted to edges from fixes near in time."""
    BAND = 0.05
    def __init__(self, edges):
        self.bands = {}
        for a, b, ts, fid in edges:
            lo, hi = int(min(a[0], b[0])/self.BAND), int(max(a[0], b[0])/self.BAND)
            for k in range(lo, hi+1):
                self.bands.setdefault(k, []).append((a, b, ts, fid))
    def covered(self, la, lo, ts, tol_m, window_s, skip_fid=None):
        k0 = int(la/self.BAND)
        best = 9e9
        for k in (k0-1, k0, k0+1):
            for a, b, ets, fid in self.bands.get(k, ()):
                if fid == skip_fid:
                    continue
                if abs(ets-ts) > window_s:
                    continue
                ax, ay = _xy(*a, la); bx, by = _xy(*b, la); px, py = _xy(la, lo, la)
                dd = _sd(px, py, ax, ay, bx, by)
                if dd < best:
                    best = dd
                    if best <= tol_m:
                        return True, best
        return False, best

def fixes_per_day(d):
    """{'YYYY-MM-DD': how many fixes the journey holds that day}, all sources.

    Every fix counts, not just hand-placed ones: what keeps a day on the journey is any fix
    at all, so a check-in sharing its date with a plotter leg is not the last of its day.
    Dates are UTC, which is what the rest of this file uses; a fix within a couple of hours
    of local midnight could in principle be the last of its *local* day and not its UTC one,
    and that is a known edge this does not chase.
    """
    out = {}
    for f in d['geojson']['features']:
        p = f['properties']
        if f['geometry']['type'] != 'Point' or not p.get('timeMs'):
            continue
        day = datetime.fromtimestamp(p['timeMs']/1000.0, UTC).strftime('%Y-%m-%d')
        out[day] = out.get(day, 0) + 1
    return out

def last_of_its_day(day, census):
    """Would deleting this fix leave its date with nothing on the journey at all?

    The tool's rule has always been that a point which is still the only record of its day
    is kept, but until 2026-08-12 it only asked whether *track* passed nearby. Track belongs
    to another fix with its own timestamp, and the coverage window reaches 36 hours, so a fix
    can be fully covered and still be the last thing standing on its date. Seven of the ten
    `Manual` candidates were exactly that — the 2022 departure fixes, added deliberately to
    give that season its missing voyage days.

    An unseen day counts as bare: guessing "there must be others" is the guess that loses
    data.
    """
    return census.get(day, 0) <= 1

def chapter_starts(d):
    """Instants, in seconds, of the chapters actually stored for this boat.

    Synthetic per-calendar-year chapters carry `id: 0` **and** `boatId: 0` and are generated
    rather than stored — see `../NFL-CHAPTERS.md`. They must not count: they would protect
    every 1 January, which is precisely a date the boat is lying still with track passing
    either side of it.
    """
    return sorted(c['start']/1000.0 for c in (d.get('chapters') or []) if c.get('boatId'))

def at_a_chapter_boundary(t, starts, window_s):
    """Is this fix one of the ones holding a chapter boundary in place?

    Such a fix looks exactly like a superseded one and is the opposite of one. A chapter is
    drawn from the first fix inside its window, so a boundary falling inside a stay renders
    wherever the boat next moved — and the cure is a fix at the berth, timestamped at the
    boundary. That berth is a place the boat lay still, so the arrival and departure tracks
    pass within metres of it and the coverage test fires every time.

    The window reaches **both ways** because the La Rochelle refinement places a *pair*, one
    an hour either side of the boundary, so the shared point becomes the berth rather than
    an 8 nm leg drawn into the wrong chapter.

    This is not hypothetical: on 2026-08-11 this script's own list held four of the eight
    boundary fixes added on 2026-08-03, and acting on it would have silently undone four
    chapter boundaries.
    """
    return any(abs(t - s) <= window_s for s in starts)

def collect(d):
    feats = d['geojson']['features']
    fixes = {}
    for f in feats:
        p = f['properties']
        if p.get('layer') != 'fixes' or not p.get('timeMs'):
            continue
        g = f['geometry']
        c = g['coordinates'] if g['type'] == 'Point' else g['coordinates'][-1]
        fixes[p['fixId']] = {'t': p['timeMs']/1000.0, 'lat': c[1], 'lon': c[0],
                                'src': p.get('source'), 'line': []}
    for f in feats:
        if f['geometry']['type'] != 'LineString':
            continue
        fid = f['properties'].get('fixId')
        if fid in fixes:
            fixes[fid]['line'].extend([(c[1], c[0]) for c in f['geometry']['coordinates']])
    for fid, v in fixes.items():
        w = v['line']
        # strip the leading connector: it is drawing order, not recorded track
        if len(w) >= 3 and FG.hav(w[0], w[1]) > 2.0:
            v['line'] = w[1:]
    return fixes

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--snapshot', required=True)
    ap.add_argument('--tolerance', type=float, default=300.0, help='metres')
    ap.add_argument('--checkin-tolerance', type=float, default=CHECKIN_TOLERANCE,
                    help='metres; check-in positions are not evidence, so they are judged '
                         'on whether real track exists nearby at all')
    ap.add_argument('--window-hours', type=float, default=36.0)
    ap.add_argument('--line-dup-threshold', type=float, default=70.0,
                    help='%% of a fix\'s own line that must be duplicated to delete it')
    ap.add_argument('--chapter-window-hours', type=float, default=2.0,
                    help='keep a hand-placed fix this close to a chapter start')
    ap.add_argument('--out', default='/tmp/prune_ids.json')
    a = ap.parse_args()
    doc = files.read_json(a.snapshot)
    fixes = collect(doc)
    starts = chapter_starts(doc)
    census = fixes_per_day(doc)
    print(f'{len(starts)} stored chapter start(s) protecting a '
          f'+/-{a.chapter_window_hours:g} h window')
    edges = []
    for fid, v in fixes.items():
        if v['src'] not in TRACK:
            continue
        w = v['line']
        for i in range(len(w)-1):
            edges.append((w[i], w[i+1], v['t'], fid))
    idx = TimedIndex(edges)
    print(f'{len(fixes)} fixes, {len(edges)} track edges indexed')
    hand = {fid: v for fid, v in fixes.items() if v['src'] in HAND}
    print(f'{len(hand)} hand-placed fixes (Check in / Manual / NFL App)\n')
    win = a.window_hours*3600
    delete, keep = [], []
    for fid, v in sorted(hand.items(), key=lambda kv: kv[1]['t']):
        t = datetime.fromtimestamp(v['t'], UTC)
        if at_a_chapter_boundary(v['t'], starts, a.chapter_window_hours*3600):
            keep.append((t, fid, v, 'holds a chapter boundary'))
            continue
        if last_of_its_day(t.strftime('%Y-%m-%d'), census):
            keep.append((t, fid, v, 'the only fix of its day'))
            continue
        w = v['line']
        tol = tolerance_for(v['src'], a.tolerance, a.checkin_tolerance)
        own_nm = sum(FG.hav(w[i], w[i+1]) for i in range(len(w)-1)) if len(w) > 1 else 0.0
        if own_nm >= 0.5:
            dup = 0.0
            for i in range(len(w)-1):
                mid = ((w[i][0]+w[i+1][0])/2, (w[i][1]+w[i+1][1])/2)
                ok, _ = idx.covered(*mid, v['t'], tol, win, skip_fid=fid)
                if ok:
                    dup += FG.hav(w[i], w[i+1])
            pc = 100*dup/own_nm
            verdict = pc >= a.line_dup_threshold
            why = f'line {own_nm:.1f} nm, {pc:.0f}% covered'
        else:
            ok, dist = idx.covered(v['lat'], v['lon'], v['t'], tol, win, skip_fid=fid)
            verdict = ok
            why = (f'point {dist:.0f} m from track' if dist < 9e8 else 'no track in window')
        (delete if verdict else keep).append((t, fid, v, why))
    print(f'{"time (UTC)":18s} {"source":11s} {"position":22s} why')
    for t, fid, v, why in delete:
        print(f'{t.strftime("%Y-%m-%d %H:%M"):18s} {v["src"]:11s} '
              f'{v["lat"]:9.5f},{v["lon"]:9.5f}   {why}')
    print(f'\n{len(delete)} superseded -> delete;  {len(keep)} kept as the only record')
    by = {}
    for t, fid, v, why in keep:
        by[v['src']] = by.get(v['src'], 0)+1
    print('   kept by source:', by)
    json.dump([str(fid) for _, fid, _, _ in delete], open(a.out, 'w'))
    print(f'   ids written to {a.out}')

if __name__ == '__main__':
    main()
