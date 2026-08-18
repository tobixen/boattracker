"""Find places where the journey's drawn line doubles back over ground it has just covered.

Tracing these by eye on the map is slow and easy to miss, which is why this exists. It reads
the *rendered* geometry — `reimport_journey.fetch()` — because a backtrack is a property of
what is drawn, not of any one source file.

## Two granularities

Inside a line, a backtrack is a shape — the geometry doubles back on itself. Between fixes it
is a bookkeeping error — the times say the boat was somewhere it had already left, and the
renderer obediently draws a straight line back to it. The second kind cannot be seen by
looking at any one line, because the offending edge belongs to no source file: **the renderer
starts every line at the previous fix's position**, so it manufactures a chord between each
pair of fixes whether or not the boat sailed it. Get the fix order wrong, or record one
moment twice, and that chord runs backwards across the map.

So there are six reports, the first two on the drawn shape and the last four on the fixes:
`hairpins`, `retraces`, `connectors`, `swaps`, `duplicates`, `windows`.

`windows` is the one that asks the vertex timestamps outright — which line covers a period
the previous fix has already passed — instead of inferring it from the drawn shape. It was
added on 2026-08-11 because a QA sweep of 2022-2025 turned up two real cases (2024-03-03 and
2024-03-14) that all five other reports were blind to: the two lines cover *different* water
at ordinary sailing speeds, so no chord lands on old track and no impossible speed appears.

## The two shapes worth finding, and why they are different

**A hairpin** is a single vertex where the line reverses: in, then straight back out along
nearly the same bearing. It is almost always an artefact — a stray vertex, or a fix whose
2-point chord was laid across a track that already existed.

**A retrace** is longer: the line covers a stretch, then comes back over it. This one is
frequently *real* — a day sail out and home, an anchorage revisited, beating to windward — so
it is reported with the elapsed time and left for the owner to judge.

The discriminator is **time**, not geometry. Real revisits take hours or days; an artefact
retraces with little or no time passing, because the vertices either share a timestamp or come
from a fix that was inserted rather than sailed. So both reports carry the elapsed time, and
`--max-hours` filters the retrace report down to the suspicious ones.

## What it deliberately does not do

It does not delete anything, and it does not rank artefact above real. Tacking upwind produces
genuine hairpins by the dozen; so does a boat swinging at anchor. `--min-leg` exists to keep
those out, and the honest use of the output is a shortlist to look at, not a fix list.

    python3 find_backtracks.py                       # all six reports, whole journey
    python3 find_backtracks.py --from 2023-01-01 --to 2023-12-31
    python3 find_backtracks.py --hairpins --min-leg 1.0
    python3 find_backtracks.py --retraces --max-hours 2
    python3 find_backtracks.py --connectors --min-back 2
    python3 find_backtracks.py --swaps --duplicates
    python3 find_backtracks.py --windows --from 2024-01-01 --to 2024-12-31
"""
import argparse
import datetime
import math

from boattracker import files
from boattracker.nfl import reimport_journey  # noqa: E402

UTC = datetime.UTC


def metres(a, b):
    """great-circle distance in metres between (lat, lon) pairs"""
    r = 6371000.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = p2 - p1, math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(h)))


def bearing(a, b):
    la1, la2 = math.radians(a[0]), math.radians(b[0])
    dl = math.radians(b[1] - a[1])
    x = math.sin(dl) * math.cos(la2)
    y = math.cos(la1) * math.sin(la2) - math.sin(la1) * math.cos(la2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def turn(b1, b2):
    """Absolute course change in degrees, 0..180."""
    return abs((b2 - b1 + 180) % 360 - 180)


def polyline(records, lo=None, hi=None):
    """The whole journey as one ordered [(lat, lon, when, fix_id)], fixes in time order.

    Consecutive duplicate positions are dropped. They are pure rendering artefact — each
    line repeats its first point and ends with the arrival repeated — and left in they
    manufacture zero-length segments whose bearing is meaningless.
    """
    rows = []
    for fix_id, rec in records.items():
        when = datetime.datetime.fromtimestamp(rec['point'][2] / 1000, UTC)
        if (lo and when < lo) or (hi and when > hi):
            continue
        rows.append((when, fix_id, rec))
    rows.sort(key=lambda r: r[0])
    out = []
    for when, fix_id, rec in rows:
        for vertex in (rec.get('line') or []):
            point = (vertex[0], vertex[1])
            if out and metres(out[-1][:2], point) < 1.0:
                continue
            out.append((point[0], point[1], when, fix_id))
    return out


def hairpins(points, min_leg_m=926, min_turn=150):
    """Vertices where the line reverses: both neighbouring legs long, course change near 180.

    `min_leg_m` defaults to half a nautical mile. Below that the reversals are tacking,
    anchor swing and harbour manoeuvring, which are real and uninteresting here.
    """
    out = []
    for i in range(1, len(points) - 1):
        a, b, c = points[i - 1][:2], points[i][:2], points[i + 1][:2]
        d1, d2 = metres(a, b), metres(b, c)
        if d1 < min_leg_m or d2 < min_leg_m:
            continue
        angle = turn(bearing(a, b), bearing(b, c))
        if angle >= min_turn:
            hours = (points[i + 1][2] - points[i - 1][2]).total_seconds() / 3600
            out.append({'index': i, 'lat': b[0], 'lon': b[1], 'turn': angle,
                        'in_nm': d1 / 1852, 'out_nm': d2 / 1852, 'hours': hours,
                        'when': points[i][2], 'fix_id': points[i][3]})
    return out


def retraces(points, tol_m=400, min_path_m=3704, max_gap=400):
    """Stretches that return within `tol_m` of a point already passed.

    `max_gap` bounds how far ahead to look, so this stays linear-ish in practice rather than
    quadratic over the whole journey. A retrace that takes more than 400 vertices to close is
    a cruise, not an artefact.
    """
    cum = [0.0]
    for a, b in zip(points, points[1:]):
        cum.append(cum[-1] + metres(a[:2], b[:2]))
    out = []
    claimed = -1
    for i in range(len(points)):
        if i <= claimed:
            continue
        best = None
        for j in range(i + 2, min(len(points), i + max_gap)):
            if cum[j] - cum[i] < min_path_m:
                continue
            d = metres(points[i][:2], points[j][:2])
            if d < tol_m and (best is None or cum[j] - cum[i] > best[1]):
                best = (j, cum[j] - cum[i], d)
        if best:
            j, path, d = best
            hours = (points[j][2] - points[i][2]).total_seconds() / 3600
            out.append({'from': i, 'to': j, 'path_nm': path / 1852, 'apart_m': d,
                        'hours': hours, 'lat': points[i][0], 'lon': points[i][1],
                        'when': points[i][2], 'fix_id': points[i][3]})
            claimed = j
    return out


def fix_sequence(records, lo=None, hi=None):
    """[{fix_id, when, lat, lon, source, line}] for every fix with a position, in time order."""
    out = []
    for fix_id, rec in records.items():
        point = rec.get('point')
        if not point or not point[2]:
            continue
        when = datetime.datetime.fromtimestamp(point[2] / 1000, UTC)
        if (lo and when < lo) or (hi and when > hi):
            continue
        out.append({'fix_id': fix_id, 'when': when, 'lat': point[0], 'lon': point[1],
                    'source': rec.get('source'), 'line': rec.get('line') or []})
    out.sort(key=lambda f: f['when'])
    return out


def connectors(points, tol_m=400, min_back_nm=1.0, min_chord_m=926, back_hours=72,
               window=3000):
    """One row per join between fixes: the chord the site draws to reach the next fix.

    That chord is not recorded track. It exists because the renderer starts every line at
    the previous fix's position, so whatever sits between two fixes in time gets a straight
    line whether or not the boat sailed it. Two things make one worth looking at:

    * `back_nm` — the chord's far end lands within `tol_m` of ground the drawn track has
      already covered, and `back_nm` says how much of the path it undoes. This is the
      "straight line to an earlier point" shape, and it means the fixes are out of order or
      one of them duplicates the other.
    * `knots` — the speed the chord implies. A long chord over a long gap is just time out
      of GSM coverage; a long chord over minutes is a wrong timestamp.

    A chord can be perfectly forward-going and still impossible, so neither test subsumes
    the other and both are reported for every join.

    Two bounds keep `back_nm` meaning what it says, and both were added because the first
    version of this report was useless without them:

    * `min_chord_m` — a chord shorter than this draws nothing anyone can see, so it is not
      scored at all. Leaving a berth and coming back to it lands on earlier track by
      definition, and on undone path alone those rank above every genuine fault: the worst
      offender in the real journey "undid" 1339 nm on a chord of 0.01 nm.
    * `back_hours` — how far back in time the line may reach to count as a backtrack. Wrong
      order and duplication both put the chord on track laid minutes or hours earlier.
      Sailing the same water next season is not this fault, and unbounded it dominates.
    """
    cum = [0.0]
    for a, b in zip(points, points[1:]):
        cum.append(cum[-1] + metres(a[:2], b[:2]))
    out = []
    for i in range(1, len(points)):
        if points[i][3] == points[i - 1][3]:
            continue
        chord = metres(points[i - 1][:2], points[i][:2])
        hours = (points[i][2] - points[i - 1][2]).total_seconds() / 3600
        back, back_at = 0.0, None
        if chord >= min_chord_m:
            for j in range(i - 2, max(-1, i - window), -1):
                if (points[i][2] - points[j][2]).total_seconds() > back_hours * 3600:
                    break
                if metres(points[j][:2], points[i][:2]) < tol_m and cum[i - 1] - cum[j] > back:
                    back, back_at = cum[i - 1] - cum[j], j
        back_nm = back / 1852 if back / 1852 >= min_back_nm else 0.0
        out.append({'index': i, 'fix_id': points[i][3], 'from_fix': points[i - 1][3],
                    'when': points[i][2], 'lat': points[i][0], 'lon': points[i][1],
                    'chord_nm': chord / 1852, 'hours': hours,
                    'knots': (chord / 1852 / hours) if hours > 0 else float('inf'),
                    'back_nm': back_nm, 'back_index': back_at if back_nm else None})
    return out


def swaps(seq, min_gain_m=1852.0):
    """Adjacent fix pairs whose timestamps look exchanged.

    Measured, not guessed: take the drawn path through four consecutive fixes A-B-C-D and
    compare it against the same four with B and C exchanged. If the exchange makes the path
    materially shorter, the times are in the wrong order — that is what draws a line up the
    coast, back down it, and up again.

    Including D is what stops a real out-and-back day from being reported. Judged on A-B-C
    alone, every turning point looks like a saving; carrying the next fix in makes the
    genuine ones come out even. The first fix is skipped for the same reason — it has no
    predecessor to be judged against, and no connector is drawn to it either.
    """
    out = []
    pos = [(f['lat'], f['lon']) for f in seq]
    for i in range(1, len(seq) - 1):
        a, b, c = pos[i - 1], pos[i], pos[i + 1]
        d = pos[i + 2] if i + 2 < len(seq) else None
        now = metres(a, b) + metres(b, c) + (metres(c, d) if d else 0.0)
        alt = metres(a, c) + metres(c, b) + (metres(b, d) if d else 0.0)
        if now - alt > min_gain_m:
            out.append({'first': seq[i]['fix_id'], 'second': seq[i + 1]['fix_id'],
                        'when': seq[i]['when'], 'other_when': seq[i + 1]['when'],
                        'lat': b[0], 'lon': b[1], 'gain_nm': (now - alt) / 1852,
                        'source': seq[i]['source'], 'other_source': seq[i + 1]['source']})
    return out


def duplicate_fixes(seq, tol_m=100.0, max_hours=6.0):
    """Fixes close enough in both place and time to be two records of one moment.

    Both bounds are needed. The boat returns to the same berths for years, so position alone
    reports every winter layup twice over; and two fixes minutes apart are perfectly normal
    when the boat is moving. It is the pair that is near in place *and* near in time that
    was entered twice.
    """
    out = []
    for i, f in enumerate(seq):
        for g in seq[i + 1:]:
            hours = (g['when'] - f['when']).total_seconds() / 3600
            if hours > max_hours:
                break
            apart = metres((f['lat'], f['lon']), (g['lat'], g['lon']))
            if apart < tol_m:
                out.append({'first': f['fix_id'], 'second': g['fix_id'], 'when': f['when'],
                            'lat': f['lat'], 'lon': f['lon'], 'apart_m': apart,
                            'hours': hours, 'source': f['source'],
                            'other_source': g['source'],
                            'vertices': (len(f['line']), len(g['line']))})
    return out


def windows(seq, min_jump_m=926.0):
    """Fixes whose own line covers a window the previous fix has already passed.

    Asked of the vertex timestamps directly, rather than inferred from the drawn shape.
    That is the point of it: `connectors` catches this class only when the chord happens
    to land within `tol_m` of already-drawn track, or implies an impossible speed. Where
    the two lines cover *different* water at ordinary sailing speeds it sees nothing, and
    2024-03-03 and 2024-03-14 are both that case — found by hand, not by the tool.

    The shape is the one behind the 180 nm Marmara defect: a short fragment carrying a
    timestamp from the middle or the end of the full leg it belongs to. The renderer draws
    the fragment, then jumps back to where the full leg begins and sails it again.

    Two things are deliberately not judged here:

    * **Untimed lines.** Many 2023 vertices carry epoch 0. Nothing follows about their
      window, and reading 1970 as "before" would report every one. So the 2023-10-13
      Menorca duplication — an untimed `NFL App` line retracing the departure — is invisible
      to this report and has to come from `retraces`.
    * **Which of the two is wrong.** The overlap says the pair is inconsistent, not which
      timestamp to move. Both lines are internally coherent in every case looked at so far.
    """
    out = []
    for prev, cur in zip(seq, seq[1:]):
        interior = [v for v in cur['line'][1:] if len(v) > 2 and v[2]]
        if not interior:
            continue
        starts = datetime.datetime.fromtimestamp(min(v[2] for v in interior) / 1000, UTC)
        overlap = (prev['when'] - starts).total_seconds() / 3600
        if overlap <= 0:
            continue
        jump = metres((prev['lat'], prev['lon']), (interior[0][0], interior[0][1]))
        if jump < min_jump_m:
            continue
        out.append({'fix_id': cur['fix_id'], 'from_fix': prev['fix_id'],
                    'when': cur['when'], 'prev_when': prev['when'], 'starts': starts,
                    'lat': cur['lat'], 'lon': cur['lon'], 'overlap_hours': overlap,
                    'jump_nm': jump / 1852, 'source': cur['source'],
                    'other_source': prev['source']})
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--snapshot', help='read a saved journey snapshot instead of the API')
    ap.add_argument('--from', dest='lo', help='first day (YYYY-MM-DD)')
    ap.add_argument('--to', dest='hi', help='last day')
    ap.add_argument('--hairpins', action='store_true', help='only the hairpin report')
    ap.add_argument('--retraces', action='store_true', help='only the retrace report')
    ap.add_argument('--connectors', action='store_true',
                    help='only the joins between fixes, where wrong order shows up')
    ap.add_argument('--swaps', action='store_true',
                    help='only the fix pairs whose timestamps look exchanged')
    ap.add_argument('--duplicates', action='store_true',
                    help='only the fixes recording one moment twice')
    ap.add_argument('--windows', action='store_true',
                    help='only the lines covering a window the previous fix has passed')
    ap.add_argument('--min-back', type=float, default=1.0,
                    help='nm of path a connector must undo to be reported (default 1)')
    ap.add_argument('--min-chord', type=float, default=0.5,
                    help='nm; shorter joins draw nothing visible and are not scored')
    ap.add_argument('--back-hours', type=float, default=72.0,
                    help='how old the landed-on track may be (default 72 h)')
    ap.add_argument('--max-knots', type=float, default=15.0,
                    help='knots above which a connector is impossible rather than a gap')
    ap.add_argument('--min-gain', type=float, default=1.0,
                    help='nm a swap must shorten the drawn path by (default 1)')
    ap.add_argument('--dup-tol', type=float, default=100.0,
                    help='metres within which two fixes are the same place (default 100)')
    ap.add_argument('--dup-hours', type=float, default=6.0,
                    help='hours within which two fixes are the same moment (default 6)')
    ap.add_argument('--min-jump', type=float, default=0.5,
                    help='nm the renderer must jump back for a window to be reported')
    ap.add_argument('--min-leg', type=float, default=0.5,
                    help='nm; both legs of a hairpin must exceed this (default 0.5)')
    ap.add_argument('--min-turn', type=float, default=150.0,
                    help='degrees of course change to count as a hairpin (default 150)')
    ap.add_argument('--tol', type=float, default=400.0,
                    help='metres within which a retrace counts as returning (default 400)')
    ap.add_argument('--min-path', type=float, default=2.0,
                    help='nm of path a retrace must cover (default 2)')
    ap.add_argument('--max-hours', type=float,
                    help='only retraces closing faster than this — the suspicious ones')
    ap.add_argument('--limit', type=int, default=40)
    a = ap.parse_args()

    day = lambda s: datetime.datetime.fromisoformat(s).replace(tzinfo=UTC) if s else None
    data = (files.read_json(a.snapshot) if a.snapshot else reimport_journey.fetch())
    records = reimport_journey.fixes_and_lines(data)
    points = polyline(records, day(a.lo), day(a.hi))
    seq = fix_sequence(records, day(a.lo), day(a.hi))
    print(f'{len(points)} vertices across {len(seq)} fixes in range\n')

    both = not (a.hairpins or a.retraces or a.connectors or a.swaps or a.duplicates
                or a.windows)
    if a.hairpins or both:
        found = hairpins(points, a.min_leg * 1852, a.min_turn)
        found.sort(key=lambda h: -min(h['in_nm'], h['out_nm']))
        print(f'== hairpins: {len(found)} vertices reversing >= {a.min_turn:.0f} deg '
              f'with both legs >= {a.min_leg} nm ==')
        for h in found[:a.limit]:
            print(f"  {h['when']:%Y-%m-%d %H:%M}Z  {h['lat']:9.5f},{h['lon']:9.5f}  "
                  f"turn {h['turn']:5.1f}  in {h['in_nm']:5.2f} nm  out {h['out_nm']:5.2f} nm  "
                  f"{h['hours']:6.1f} h  fix {h['fix_id']}")
        if not found:
            print('  none')

    if a.retraces or both:
        found = retraces(points, a.tol, a.min_path * 1852)
        if a.max_hours is not None:
            found = [r for r in found if r['hours'] <= a.max_hours]
        found.sort(key=lambda r: -r['path_nm'])
        print(f"\n== retraces: {len(found)} returns to within {a.tol:.0f} m after "
              f">= {a.min_path} nm of path ==")
        print('   long elapsed times are usually real revisits; short ones are the suspects')
        for r in found[:a.limit]:
            print(f"  {r['when']:%Y-%m-%d %H:%M}Z  {r['lat']:9.5f},{r['lon']:9.5f}  "
                  f"path {r['path_nm']:6.1f} nm  back within {r['apart_m']:4.0f} m  "
                  f"after {r['hours']:7.1f} h  fix {r['fix_id']}")
        if not found:
            print('  none')

    if a.connectors or both:
        rows = connectors(points, a.tol, a.min_back, a.min_chord * 1852, a.back_hours)
        bad = [c for c in rows if c['back_nm'] or c['knots'] > a.max_knots]
        bad.sort(key=lambda c: -max(c['back_nm'], 0))
        print(f'\n== connectors: {len(bad)} of {len(rows)} joins between fixes are suspect ==')
        print(f"   back = nm of already-drawn path the join undoes; > {a.max_knots:.0f} kn "
              'is a wrong timestamp, not a coverage gap')
        for c in bad[:a.limit]:
            flag = 'BACK' if c['back_nm'] else '    '
            speed = f"{c['knots']:6.1f}" if c['knots'] != float('inf') else '   inf'
            print(f"  {c['when']:%Y-%m-%d %H:%M}Z  {c['lat']:9.5f},{c['lon']:9.5f}  {flag} "
                  f"back {c['back_nm']:6.2f} nm  chord {c['chord_nm']:6.2f} nm  "
                  f"{c['hours']:7.2f} h  {speed} kn  fix {c['from_fix']} -> {c['fix_id']}")
        if not bad:
            print('  none')

    if a.swaps or both:
        found = swaps(seq, a.min_gain * 1852)
        found.sort(key=lambda s: -s['gain_nm'])
        print(f'\n== swaps: {len(found)} fix pairs the drawn path would be shorter without ==')
        print('   these are candidates for exchanged timestamps; check the dates before acting')
        for s in found[:a.limit]:
            print(f"  {s['when']:%Y-%m-%d %H:%M}Z / {s['other_when']:%m-%d %H:%M}Z  "
                  f"{s['lat']:9.5f},{s['lon']:9.5f}  saves {s['gain_nm']:7.2f} nm  "
                  f"fix {s['first']} <-> {s['second']}  ({s['source']} / {s['other_source']})")
        if not found:
            print('  none')

    if a.duplicates or both:
        found = duplicate_fixes(seq, a.dup_tol, a.dup_hours)
        found.sort(key=lambda d: d['apart_m'])
        print(f"\n== duplicates: {len(found)} fix pairs within {a.dup_tol:.0f} m and "
              f"{a.dup_hours:g} h of each other ==")
        for d in found[:a.limit]:
            print(f"  {d['when']:%Y-%m-%d %H:%M}Z  {d['lat']:9.5f},{d['lon']:9.5f}  "
                  f"{d['apart_m']:6.1f} m apart  {d['hours']:5.2f} h  "
                  f"fix {d['first']} + {d['second']}  ({d['source']} / {d['other_source']})  "
                  f"vertices {d['vertices'][0]}+{d['vertices'][1]}")
        if not found:
            print('  none')

    if a.windows or both:
        found = windows(seq, a.min_jump * 1852)
        found.sort(key=lambda w: -w['jump_nm'])
        total = sum(w['jump_nm'] for w in found)
        print(f'\n== windows: {len(found)} lines starting before the previous fix\'s time, '
              f'{total:.1f} nm of drawn jump ==')
        print('   the overlap is what is certain; which of the two timestamps is wrong is not')
        for w in found[:a.limit]:
            print(f"  {w['when']:%Y-%m-%d %H:%M}Z  {w['lat']:9.5f},{w['lon']:9.5f}  "
                  f"jump {w['jump_nm']:7.2f} nm  overlap {w['overlap_hours']:6.2f} h  "
                  f"line starts {w['starts']:%m-%d %H:%M}Z  "
                  f"fix {w['from_fix']} -> {w['fix_id']}  "
                  f"({w['other_source']} / {w['source']})")
        if not found:
            print('  none')


if __name__ == '__main__':
    main()
