"""Find gaps in the noforeignland journey — plotter track that the site does not hold.

Four modes. **Use `partial`** (the default) unless there is a specific reason not to; the others
answer narrower questions and two of them have known blind spots.

**`partial`** — walks every date-plausible source segment **edge by edge** and reports the runs
that are not on the journey, however short. This is the only mode that sees the commonest case: a
segment mostly present, missing just the stretch where the tracker had dropped out. `Track 4` s95
is 78% present, and the missing 17% is exactly where the journey drew a 15 nm chord across the
peninsula outside Marmaris — `journey-gaps` and `uncovered` both called 2024 clean with that on
the map, because both judged coverage per whole segment.

**`journey-gaps`** — works from the journey outwards instead of from the sources inwards. For each
pair of consecutive fixes it asks whether the boat jumped, and if so whether local track bridges
it, following the plotter's own segment chain across the jump. Good for "what large stretches are
simply absent", and it needs no track dating because the two fix positions define the corridor.
Blind to anything smaller than `--min-jump`.

**`chords`** — straight runs *inside* a journey line. These matter for 2023 and 2024, where most
of the journey came from the on-board GPS/GSM tracker: it timestamps well and reports live, but is
coarser than the plotter and stops outside cellphone coverage, so offshore passages arrive as long
straight lines. Where plotter track covers such a chord, the plotter geometry is better.

**`uncovered`** — **superseded, kept only for comparison.** Judges each segment as present or
absent as a whole, and so misses partial gaps by construction. It also compares against journey
lines from the query window only, rather than each segment's own dates, which makes it report
water that is covered by a fix sitting just outside the window. On 2025-09 it claims 68 nm missing
where `partial` correctly finds none. Do not use it to decide anything.

## Track dating is automatic

Source segments are restricted to tracks that could have been recording in the query window, via
`track_dates.py`. That map is derived from the dates already encoded in `nfl-export/` filenames
plus the monotonicity of the plotter's track counter, so **every export improves the next scan**.

Before that existed, every run needed `--tracks` by hand and forgetting it produced nonsense — a
May 2024 gap "bridged" by `Track 61` from July 2026, because Raymarine GPX carries no timestamps
and the boat crossed the same water for years. `--tracks` still overrides; `--no-date-filter`
disables the map for a deliberately unrestricted look.

**The limit worth knowing:** a track with too few dated segments cannot be scanned usefully.
`Track 1`, `Track 3` and `Track 7` are in that state — Track 7 has 75 segments and 4 dated, Track
1 has one across fifty-odd. Run against them, `partial` reported 2002 nm missing for 2024, nearly
all of it artefact from windows weeks off the true dates. **If a scan reports implausibly much,
suspect the date map before believing the number.** Anchoring a few segments per track against the
diary is what fixes it.

## Two traps this tool exists to avoid

**Do not decide coverage from filenames.** Checking which `nfl-export/nfl-YYYY-MM-*.gpx` files
exist gave wrong answers twice: once claiming `Track 41` s0 was missing when it had been uploaded
under a July filename, and once declaring August complete while 71.92 nm of the Varna approach was
absent, because the scan was bounded by track number instead of by date. Coverage is a geometric
question; ask it geometrically.

**Strip the leading connector before measuring.** Every rendered line begins with the *previous*
fix's position, so a line whose track starts far away carries a long false first edge. Left in,
those edges make missing water measure as covered — they run straight through the very water they
are standing in for.

## Usage

    # the normal question: what plotter track is not on the site?
    python3 find_gaps.py --from 2025-09-01 --to 2025-09-30

    # large absent stretches, and whether a segment chain bridges them
    python3 find_gaps.py --from 2024-01-01 --to 2024-12-31 --mode journey-gaps --min-jump 8

    # tracker straight lines that plotter geometry could replace
    python3 find_gaps.py --from 2023-01-01 --to 2024-12-31 --mode chords --min-chord 5

    # a poorly-dated track: bound it by hand instead of trusting the map
    python3 find_gaps.py --from 2024-01-01 --to 2024-12-31 --tracks 'Track 4'

`--cache <file>` reuses a saved journey JSON instead of re-fetching, which matters because these
scans are slow and usually get run several times over the same data.

Acting on what it finds: `export_partial_runs.py` for a within-segment run, or a per-period
exporter for whole legs. See `IMPROVE-TRACKS.md` for the full cycle.
"""
import argparse
import json
import math
import os
import re
import subprocess
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

## `files` is a keyword parameter of source_segments(), so the module would be
## shadowed inside it; the functions are imported by name here instead.
from boattracker import config, geo
from boattracker.files import read_json, read_text, write_json
from boattracker.nfl import track_dates as TD

OSLO = ZoneInfo('Europe/Oslo')
T = config.DATA
R = geo.R_EARTH
__getattr__ = config.lazy_module_getattr('JOURNEY_URL')

## nautical miles here, metres in `leg_export.hav`; the two units are why there are two
## names for one function.  `FG.hav` is imported by name across the tree - see
## `test_geo.py` - so it stays a module attribute rather than becoming a call through geo.
hav = geo.hav_nm

def _xy(la, lo, la0):
    p = math.pi/180
    return (lo*p*R*math.cos(la0*p), la*p*R)

def _seg_dist(px, py, ax, ay, bx, by):
    dx, dy = bx-ax, by-ay
    if dx == 0 and dy == 0:
        return math.hypot(px-ax, py-ay)
    t = max(0.0, min(1.0, ((px-ax)*dx + (py-ay)*dy)/(dx*dx+dy*dy)))
    return math.hypot(px-(ax+t*dx), py-(ay+t*dy))

def fetch(cache):
    if cache and os.path.exists(cache):
        return read_json(cache)
    out = subprocess.run(['curl', '-s', '-m', '60', config.JOURNEY_URL], capture_output=True, text=True)
    d = json.loads(out.stdout)
    if cache:
        write_json(cache, d)
    return d

def journey_lines(d, lo_date, hi_date, chord_cut=2.0):
    """Rendered polylines for fixes in the window, with the leading connector removed.

    Returns [(fix_time, [(lat, lon), ...])].  `chord_cut` is the step size in nm above
    which the first edge is treated as a connector rather than real track.
    """
    feats = d['geojson']['features']
    tms = {f['properties']['fixId']: f['properties'].get('timeMs')
           for f in feats if f['properties'].get('layer') == 'fixes'}
    out = []
    for f in feats:
        if f['geometry']['type'] != 'LineString':
            continue
        ms = tms.get(f['properties'].get('fixId'))
        if not ms:
            continue
        t = datetime.fromtimestamp(ms/1000, UTC)
        if not (lo_date <= t.strftime('%Y-%m-%d') <= hi_date):
            continue
        v = [(c[1], c[0]) for c in f['geometry']['coordinates']]
        if len(v) >= 3 and hav(v[0], v[1]) > chord_cut:
            v = v[1:]
        if len(v) >= 2:
            out.append((t, v))
    out.sort()
    return out

_pat = re.compile(r'lon="([^"]+)" lat="([^"]+)"')
def is_survey_file(fn):
    """Is this one of the local Raymarine exports the scan should read?

    Excludes the `nfl-` exports — those are what was *uploaded*, and measuring coverage
    from them would be circular. Excludes `test_raymarine.gpx` too: it is the one .gpx
    `.gitignore` keeps, because the tests need a sample, and it was quietly contributing
    four `Track 1` segments to real gap figures.
    """
    return fn.endswith('.gpx') and not fn.startswith('nfl-') and fn != 'test_raymarine.gpx'

def dedupe(segs):
    """One entry per distinct stretch of water, keyed on the points themselves.

    **Segment indices are file-local.** The hand-cropped delivery files are excerpts of the
    plotter's own `Track 1` and each renumbers from zero, so `Track 1 s0` names different
    water in each of the nine files carrying that name. Keyed on `(name, si)` this kept
    whichever file `sorted()` reached first and dropped the rest — 459 of 1244 segments, of
    which 426 genuinely were duplicates and about 33 were not.

    Keying on the file instead would be no better: `france-etc.gpx` and `raymarine_rest.gpx`
    are near-copies of one export, and their shared segments would then be counted twice.
    The points are the only thing that identifies a segment across both problems.
    """
    out, seen = [], set()
    for fn, name, si, p in segs:
        key = tuple(p)
        if key in seen:
            continue
        seen.add(key)
        out.append((fn, name, si, p))
    return out

def eligible(name, tracks, window):
    """Should this track be searched: is it named, and could it be from this period?

    The two tests are independent, and reading them as one is the bug this replaced.
    `source_segments` had `if window and not tracks and not TD.overlaps(...)`, so **naming a
    track switched the date filter off**, and a segment from any month of it became eligible.
    That is how slices of `Track 4 s69` and `s71`, months away, were offered to fill gaps in
    the 2024-04-03 leg; only a geometric plausibility check stopped them going in.

    Naming a track narrows the search. It never widens the dates.
    """
    if tracks and name not in tracks:
        return False
    if window and not TD.overlaps(name, *window):
        return False
    return True

def segment_eligible(name, si, window):
    """Could *this segment* be from this period?  (opt-in: `strict_dates=True`)

    `eligible()` answers for a whole track, and that is too coarse to be the only defence:
    `Track 4` runs 2023-12 to 2024-05, so every one of its segments passes a filter set to a
    single April day. The slices wrongly offered for 2024-04-03 were from that same track,
    months apart, and only a geometric check stopped them.

    `track_dates.segment_window()` brackets a single segment by interpolating between the
    dated ones around it, so it can separate them. **An undated segment is allowed** — unknown
    never means excluded here, which is the rule the whole date map runs on.

    **Opt-in, and deliberately so.** Dropping a segment changes which copy of a duplicated
    one survives `dedupe()`, and the survivor carries a different `si` and therefore a
    different date bracket — so switching this on moves coverage totals for reasons that have
    nothing to do with coverage. The gap scans keep their old behaviour; only the callers that
    pick *candidate slices to upload* ask for this, where a wrong slice is the whole risk.
    """
    if not window:
        return True
    win = TD.segment_window(name, si)
    if not win:
        return True
    lo, hi = window
    lo = date.fromisoformat(lo) if isinstance(lo, str) else lo
    hi = date.fromisoformat(hi) if isinstance(hi, str) else hi
    return not (win[1] < lo or win[0] > hi)

def source_segments(files=None, min_excursion=0.25, min_points=20, tracks=None,
                    window=None, strict_dates=False):
    """Every moving segment across the local Raymarine exports.

    `tracks` restricts to named tracks. Raymarine exports carry no timestamps, so the tool
    cannot date a segment on its own; when the journey window overlaps water the boat has
    visited in more than one season — Varna especially — an unfiltered run will report
    segments from other years as 'missing'. Pass the tracks belonging to the period.
    """
    if files is None:
        # the 2023 delivery is held in hand-cropped files, not the Tracks* exports, so both
        # sets are scanned. Two of the crops are invalid XML (unclosed <trkseg>); the regex
        # reader here tolerates that where an XML parser would not.
        files = sorted(f for f in os.listdir(T) if is_survey_file(f))
    segs = []
    for fn in files:
        try:
            txt = read_text(f'{T}/{fn}', errors='replace')
        except OSError:
            continue
        for trk in re.findall(r'<trk>.*?</trk>', txt, re.S):
            m = re.search(r'<name>(.*?)</name>', trk)
            if not m:
                continue
            name = m.group(1)
            # Left exactly as it was, deliberately. `eligible()` below states the corrected
            # rule — naming a track must not switch dating off — but these two lines are what
            # every `find_gaps` mode has always used, and changing them changes published
            # coverage figures. Callers that pick candidate slices to upload ask for the
            # corrected rule explicitly instead.
            if tracks and name not in tracks:
                continue
            # drop tracks that provably belong to another season
            if window and not tracks and not TD.overlaps(name, *window):
                continue
            for si, seg in enumerate(re.findall(r'<trkseg>.*?</trkseg>', trk, re.S)):
                p = [(float(la), float(lo)) for lo, la in _pat.findall(seg)]
                p = [q for q in p if -90 < q[0] < 90 and -180 < q[1] < 180]
                if len(p) < min_points:
                    continue
                if max(hav(p[0], q) for q in p) < min_excursion:
                    continue
                if strict_dates and not segment_eligible(name, si, window):
                    continue
                segs.append((fn, name, si, p))
    return drop_off_planet(segs)


def drop_off_planet(segs, max_nm=3000.0):
    """Remove segments the plotter recorded in the wrong hemisphere.

    The diary, 2026-08-07: *"the navigator several times dropped GPS, and then later
    decided we were in Peru, cruising in a circle in 109 knots."* `Tracks.gpx` carries
    484 such points across 11 whole segments of Tracks 64Xxx and 65, all at
    -12.04, -77.05. They pass the lat/lon range check above, so without this they are
    reported as 40.5 nm of missing track for ever.

    Judged **within each track**, against that track's own point-weighted median: a
    track is one continuous recording period, so nothing real is 3000 nm from the middle
    of its own track, while Peru is ~7000 nm from the Black Sea. Measuring against the
    whole corpus instead would risk dropping real segments, since the corpus spans
    Norway to Turkey.
    """
    groups = {}
    for i, (fn, name, si, p) in enumerate(segs):
        groups.setdefault((fn, name), []).append(i)
    drop = set()
    for members in groups.values():
        if len(members) < 3:
            continue
        cents = [(sum(q[0] for q in segs[i][3]) / len(segs[i][3]),
                  sum(q[1] for q in segs[i][3]) / len(segs[i][3])) for i in members]
        # Median over every *point* in the track, not over segment centroids: the
        # plotter split its Peru episode into seven short segments against Track 65's
        # four real ones, so a per-segment median lands in Peru and throws the real
        # track away instead. Point-weighted, it is 335 points against 9650.
        pts = [q for i in members for q in segs[i][3]]
        mid = (sorted(q[0] for q in pts)[len(pts) // 2],
               sorted(q[1] for q in pts)[len(pts) // 2])
        for i, c in zip(members, cents):
            if hav(c, mid) > max_nm:
                drop.add(i)
    return [s for i, s in enumerate(segs) if i not in drop]

class Index:
    """Point-to-polyline distance over a set of lines, with a latitude-band prefilter."""
    BAND = 0.05
    def __init__(self, lines):
        self.bands = {}
        for v in lines:
            for a, b in zip(v, v[1:]):
                lo_b, hi_b = int(min(a[0], b[0])/self.BAND), int(max(a[0], b[0])/self.BAND)
                for k in range(lo_b, hi_b+1):
                    self.bands.setdefault(k, []).append((a, b))
    def distance(self, la, lo, stop_at=300.0):
        best = 9e9
        k0 = int(la/self.BAND)
        for k in (k0-1, k0, k0+1):
            for a, b in self.bands.get(k, ()):
                ax, ay = _xy(*a, la); bx, by = _xy(*b, la); px, py = _xy(la, lo, la)
                dd = _seg_dist(px, py, ax, ay, bx, by)
                if dd < best:
                    best = dd
                    if best < stop_at:
                        return best
        return best

def mode_uncovered(d, args):
    """SUPERSEDED by mode_partial; kept for comparison only.

    Judges each segment present or absent as a whole, so it cannot see a segment that is mostly
    uploaded with a stretch missing — which is the usual shape. It also measures against journey
    lines from the query window rather than each segment's own dates, so water covered by a fix
    just outside the window reads as missing. Both faults inflate its answer.
    """
    lines = journey_lines(d, args.from_date, args.to_date)
    print(f'{len(lines)} journey lines in {args.from_date}..{args.to_date}')
    idx = Index([v for _, v in lines])
    segs = source_segments(files=args.files, tracks=args.tracks, window=args.window)
    print(f'{len(segs)} moving source segments\n')
    print(f'{"file":22s} {"segment":16s} {"nm":>7s} {"cov":>5s}  endpoints')
    total = 0.0
    for fn, name, si, p in segs:
        samp = p[::max(1, len(p)//40)]
        cov = 100*sum(1 for q in samp if idx.distance(*q) <= args.tolerance)/len(samp)
        if cov >= args.min_coverage:
            continue
        # only report segments lying inside the journey's own bounding area, else every
        # track from another year shows up
        if idx.distance(*p[0]) > 200000 and idx.distance(*p[-1]) > 200000:
            continue
        nm = sum(hav(p[i], p[i+1]) for i in range(len(p)-1))
        if nm < args.min_nm:
            continue
        total += nm
        print(f'{fn:22s} {name+" s"+str(si):16s} {nm:7.2f} {cov:4.0f}%  '
              f'{p[0][0]:.4f},{p[0][1]:.4f} -> {p[-1][0]:.4f},{p[-1][1]:.4f}')
    print(f'\n{total:.1f} nm of local track not present on the journey')

def mode_chords(d, args):
    """Long straight runs inside journey lines, and whether plotter data covers them."""
    lines = journey_lines(d, args.from_date, args.to_date)
    segs = source_segments(files=args.files, tracks=args.tracks, window=args.window)
    idx = Index([p for _, _, _, p in segs])
    print(f'{len(lines)} journey lines, {len(segs)} source segments\n')
    print(f'{"fix (Oslo)":18s} {"chord":>7s}  {"plotter?":9s} from -> to')
    n = cover = 0
    tot = covnm = 0.0
    for t, v in lines:
        for i in range(len(v)-1):
            step = hav(v[i], v[i+1])
            if step < args.min_chord:
                continue
            n += 1; tot += step
            # sample along the chord; is there plotter track near it?
            hits = 0
            for k in range(1, 10):
                la = v[i][0] + (v[i+1][0]-v[i][0])*k/10
                lo = v[i][1] + (v[i+1][1]-v[i][1])*k/10
                if idx.distance(la, lo) <= args.tolerance*10:
                    hits += 1
            has = hits >= 5
            if has:
                cover += 1; covnm += step
            print(f'{t.astimezone(OSLO).strftime("%Y-%m-%d %H:%M"):18s} {step:7.2f}  '
                  f'{"YES" if has else "-":9s} {v[i][0]:.4f},{v[i][1]:.4f} -> '
                  f'{v[i+1][0]:.4f},{v[i+1][1]:.4f}')
    print(f'\n{n} chords over {args.min_chord} nm, {tot:.1f} nm total')
    print(f'{cover} of them ({covnm:.1f} nm) have Raymarine track that could replace them')

def journey_fixes(d, lo, hi):
    out = []
    for f in d['geojson']['features']:
        p = f['properties']
        if p.get('layer') != 'fixes' or not p.get('timeMs'):
            continue
        t = datetime.fromtimestamp(p['timeMs']/1000, UTC)
        if not (lo <= t.strftime('%Y-%m-%d') <= hi):
            continue
        g = f['geometry']
        c = g['coordinates'] if g['type'] == 'Point' else g['coordinates'][-1]
        out.append((t, c[1], c[0], p.get('source'), p['fixId']))
    out.sort()
    return out

def uncovered_runs(p, idx, tol_m, min_nm):
    """Contiguous stretches of a segment that the journey does not hold.

    Per-edge, not per-segment: a segment is usually part-present, and the missing part is the
    whole point. Returns [(first_index, last_index_exclusive, nm)].
    """
    flags = []
    for i in range(len(p)-1):
        mid = ((p[i][0]+p[i+1][0])/2, (p[i][1]+p[i+1][1])/2)
        flags.append(idx.distance(*mid) <= tol_m)
    runs, cur = [], None
    for i, ok in enumerate(flags):
        if not ok:
            cur = [i, i] if cur is None else [cur[0], i]
        elif cur:
            runs.append(cur); cur = None
    if cur:
        runs.append(cur)
    out = []
    for a, b in runs:
        nm = sum(hav(p[k], p[k+1]) for k in range(a, b+1))
        if nm >= min_nm:
            out.append((a, b+1, nm))
    return out

def chain_bridge(by_track, p1, p2, jidx, tol_m, max_nm):
    """Walk the plotter's own segment chain from p1 towards p2 and total what is missing.

    A gap is rarely bridged by one segment. The 2024-04-29 gap took five (Track 4 s104 to s108
    plus part of s109), so the test follows the chain: find the segment ending at p1, then step
    through the following segments of the same track while they stay contiguous, until p2 is
    reached. Requiring a single segment to span both ends misses these entirely; requiring only
    that a segment pass near either end matches half the Aegean, because the boat crossed the
    same water for years.

    Missing distance is measured as **uncovered runs inside each segment**, not by judging a
    segment present or absent as a whole. A part-present segment otherwise counts as wholly
    missing, which kept a gap being reported for several rounds after it had been filled.
    """
    best = None
    for name, segs in by_track.items():
        # the segment whose END is closest to p1 is where the chain starts
        cands = sorted(((hav(p[-1], p1), si) for si, p in segs.items()))
        if not cands or cands[0][0] > 1.0:
            continue
        start = cands[0][1]
        chain, walked, prev_end = [], 0.0, segs[start][-1]
        for si in sorted(k for k in segs if k > start):
            p = segs[si]
            if hav(prev_end, p[0]) > 1.0:      # chain broken: the plotter was off
                break
            # p2 may sit anywhere along a segment, not only at its end - the gap's closing fix
            # is often mid-passage. Reaching it partway still bridges the gap.
            reach = min(range(len(p)), key=lambda k: hav(p[k], p2))
            if hav(p[reach], p2) <= 1.5:
                head = p[:reach+1]
                miss = sum(nm for _, _, nm in uncovered_runs(head, jidx, tol_m, 0.3))
                chain.append((name, si, miss, 0.0 if miss else 100.0))
                uncov = sum(l for _, _, l, _c in chain)
                if best is None or uncov > best[1]:
                    best = (chain, uncov)
                break
            leg = sum(hav(p[k], p[k+1]) for k in range(len(p)-1))
            miss = sum(nm for _, _, nm in uncovered_runs(p, jidx, tol_m, 0.3))
            cov = 100*(1-miss/leg) if leg else 100.0
            chain.append((name, si, miss, cov))
            walked += leg
            prev_end = p[-1]
            if walked > max_nm:
                break
    return best

def mode_partial(d, args):
    """every stretch of local plotter track that the journey does not hold.

    Coverage is judged **per segment against its own date window**, not against a single
    user-supplied window. Judging everything against one window makes January track data look
    missing when compared with April journey lines, which is how the first run of this mode
    reported 5227 nm. `track_dates.segment_window` narrows each segment by interpolating
    between the dated segments of its own track.
    """
    # a wide pool of journey lines, bucketed by month so each segment can be compared with
    # only the months its own window touches
    pool = journey_lines(d, '2000-01-01', '2100-01-01')
    buckets = {}
    for t, v in pool:
        buckets.setdefault(t.strftime('%Y-%m'), []).append(v)
    idx_cache = {}
    def index_for(win):
        lo, hi = win
        keys = []
        y, m = lo.year, lo.month
        while (y, m) <= (hi.year, hi.month):
            keys.append(f'{y:04d}-{m:02d}')
            m += 1
            if m > 12:
                y, m = y+1, 1
        ck = tuple(keys)
        if ck not in idx_cache:
            vs = [v for k in keys for v in buckets.get(k, ())]
            idx_cache[ck] = Index(vs)
        return idx_cache[ck]
    segs = source_segments(files=args.files, tracks=args.tracks, window=args.window,
                           min_excursion=0.0, min_points=2)
    print(f'{len(pool)} journey lines pooled, {len(segs)} date-plausible source segments\n')
    print(f'{"segment":18s} {"file":14s} {"seg nm":>7s} {"missing":>8s} '
          f'{"edges":>11s}  from -> to')
    tot = 0.0
    rows = []
    whole = Index([v for _, v in pool])
    undated = 0
    for fn, name, si, p in dedupe(segs):
        win = TD.segment_window(name, si)
        if win is None:
            # The date map has nothing to say about this segment. Compare it against the
            # whole journey rather than skipping it: an undated segment whose water is on
            # the journey *somewhere* is covered, and pretending otherwise is how the 2022
            # delivery came to be reported as thousands of missing miles.
            idx, undated = whole, undated + 1
        else:
            idx = index_for(win)
        for a, b, nm in uncovered_runs(p, idx, args.tolerance, args.min_nm):
            tot += nm
            rows.append((nm, name, si, a, b, p, win, fn))
    for nm, name, si, a, b, p, win, fn in sorted(rows, key=lambda r: -r[0])[:args.limit]:
        segnm = sum(hav(p[i], p[i+1]) for i in range(len(p)-1))
        # the file is part of the segment's identity, because si is file-local
        # `A if C else B` binds looser than implicit string concatenation, so building the
        # window text separately is not a style choice - inlining it printed the bare word
        # for undated rows and swallowed the whole line.
        wtxt = f'[{win[0]}..{win[1]}]' if win else '[undated]'
        print(f'{name+" s"+str(si):18s} {fn[:14]:14s} {segnm:7.2f} {nm:8.2f} '
              f'{str(a)+".."+str(b):>11s}  '
              f'{p[a][0]:.4f},{p[a][1]:.4f} -> {p[b][0]:.4f},{p[b][1]:.4f}  {wtxt}')
    if len(rows) > args.limit:
        print(f'   ... {len(rows)-args.limit} more runs not shown '
              f'(raise --limit to see them)')
    print(f'\n{len(rows)} uncovered runs of {args.min_nm}+ nm, {tot:.1f} nm in total')
    if undated:
        print(f'   {undated} segment(s) had no usable date window and were compared '
              f'against the whole journey')

def mode_journey_gaps(d, args):
    """for each jump between consecutive fixes, is there local track to bridge it?"""
    fixes = journey_fixes(d, args.from_date, args.to_date)
    lines = journey_lines(d, args.from_date, args.to_date)
    jidx = Index([v for _, v in lines])
    segs = source_segments(files=args.files, tracks=args.tracks,
                           min_excursion=0.0, min_points=2, window=args.window)
    by_track = {}
    for fn, name, si, p in dedupe(segs):
        by_track.setdefault(name, {}).setdefault(si, p)
    print(f'{len(fixes)} fixes, {len(segs)} source segments, '
          f'{len(by_track)} tracks\n')
    print(f'{"gap starts (UTC)":18s} {"hours":>6s} {"jump":>7s} {"bridgeable":>10s}  segments')
    tot_gap = tot_fix = 0.0
    rows = []
    for i in range(len(fixes)-1):
        t1, la1, lo1, s1, f1 = fixes[i]
        t2, la2, lo2, s2, f2 = fixes[i+1]
        jump = hav((la1, lo1), (la2, lo2))
        if jump < args.min_jump:
            continue
        hrs = (t2-t1).total_seconds()/3600
        got = chain_bridge(by_track, (la1, lo1), (la2, lo2), jidx,
                           args.tolerance, max_nm=max(60.0, jump*4))
        nm_found = got[1] if got else 0.0
        if nm_found < args.min_nm:
            nm_found = 0.0
            got = None
        tot_gap += jump; tot_fix += nm_found
        rows.append((t1, hrs, jump, nm_found, got))
        names = ''
        if got:
            names = ', '.join(f'{n} s{si}' for n, si, _, c in got[0] if c < 50)
        print(f'{t1.strftime("%Y-%m-%d %H:%M"):18s} {hrs:6.1f} {jump:7.2f} '
              f'{nm_found:9.1f}  {names[:62]}')
    print(f'\n{len(rows)} jumps over {args.min_jump} nm, {tot_gap:.0f} nm of jump')
    good = [r for r in rows if r[3] > 0]
    print(f'{len(good)} have local track available, {tot_fix:.0f} nm of it')

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--from', dest='from_date', required=True)
    ap.add_argument('--to', dest='to_date', required=True)
    ap.add_argument('--mode',
                    choices=('partial', 'uncovered', 'chords', 'journey-gaps'),
                    default='partial',
                    help='partial (default, recommended); journey-gaps for large absent '
                         'stretches; chords for tracker straight lines; uncovered is '
                         'SUPERSEDED and misses partial gaps by construction')
    ap.add_argument('--limit', type=int, default=25)
    ap.add_argument('--min-jump', type=float, default=5.0,
                    help='nm between consecutive fixes to count as a gap')
    ap.add_argument('--tolerance', type=float, default=300.0,
                    help='metres; how close counts as covered (default 300)')
    ap.add_argument('--min-coverage', type=float, default=80.0)
    ap.add_argument('--min-nm', type=float, default=0.3)
    ap.add_argument('--min-chord', type=float, default=3.0)
    ap.add_argument('--tracks', default=None,
                    help='comma-separated track names to consider, e.g. '
                         '"Track 55,Track 56". Raymarine tracks have no timestamps, so '
                         'without this the tool cannot tell one season from another in '
                         'water the boat revisits.')
    ap.add_argument('--files', default=None,
                    help='comma-separated source GPX filenames; default is every .gpx in '
                         'the tracker directory')
    ap.add_argument('--no-date-filter', action='store_true',
                    help='do not restrict source tracks by their known date range')
    ap.add_argument('--cache', default=None, help='reuse a saved journey JSON')
    args = ap.parse_args()
    args.files = [x.strip() for x in args.files.split(',')] if args.files else None
    args.window = None if args.no_date_filter else (args.from_date, args.to_date)
    args.tracks = {x.strip() for x in args.tracks.split(',')} if args.tracks else None
    d = fetch(args.cache)
    {'chords': mode_chords, 'journey-gaps': mode_journey_gaps,
     'partial': mode_partial}.get(args.mode, mode_uncovered)(d, args)

if __name__ == '__main__':
    main()
