"""Approximate date range for each Raymarine track.

Raymarine GPX carries no timestamps, and for a long time that was treated as meaning the
tracks are undated — so every gap scan needed `--tracks` passed by hand, and forgetting it
produced nonsense like a May 2024 gap "bridged" by a July 2026 track.

But the tracks are not really undated. Three things pin them down:

1. **The consolidation work already done.** Every file in `nfl-export/` is named
   `nfl-<date>-track<N>s<M>.gpx`, so each exported segment states its own date. That covers
   58 track numbers from 2023-06 to 2026-07 and is the authoritative source here.
2. **Track numbers are monotonic.** The plotter increments its counter over time, so a track
   with no exports of its own is bounded by its numbered neighbours.
3. **File modification times** bound anything later than the newest export, since a track
   cannot postdate the file it was exported into.

Named tracks (`Med 2023`, `ToSantorini2024`) are handled differently. They are long
multi-month delivery or season tracks with only a handful of exported segments, so bounding
them from those exports gives a range far too narrow — it would reject 2023-06-29 for
`Med 2023`, which is plainly wrong. Instead the **year in the name** is used and the whole of
that year allowed. That is weak, but it is information the name genuinely carries, and it
still excludes the cross-season matches this filter exists to stop.

The result is approximate — a track's true span can extend a little beyond its exported
segments — so ranges are padded. It is used to *exclude* obviously-wrong candidates, not to
date anything, and a padded range that is slightly too wide is the safe direction of error.
"""
import glob
import os
import re
from datetime import date, timedelta

from boattracker import config

T = config.DATA
PAD_DAYS = 3
MIN_DATED_TO_INTERPOLATE = 2

def _norm(name):
    """'Track 57.202509' -> '57_202509', 'Med 2023' -> 'med2023'"""
    # The plotter's names carry ad-hoc alphabetic suffixes - 'Track 26P', 'Track 67W',
    # 'Track 64Xxx' - which are the owner's own annotations, not part of the counter.
    # Matching only 'P' left 64Xxx and 67W permanently undated, so every gap scan
    # compared them against the whole journey and reported their water as missing.
    m = re.match(r'Track\s+(\d+)(?:\.(\d+))?[A-Za-z]*$', name.strip())
    if m:
        return m.group(1) + ('_' + m.group(2) if m.group(2) else '')
    return re.sub(r'[^a-z0-9]', '', name.lower())

def parse_export_names():
    """[(track key, segment index, date, is_numbered)] for every file in nfl-export/.

    One parser, used by both callers. It was duplicated once and only one copy got fixed, with
    the result that exports this project had just written were invisible to its own date map.
    """
    out = []
    for fp in glob.glob(f'{T}/nfl-export/*.gpx'):
        b = os.path.basename(fp)
        md = re.match(r'nfl-(\d{4}-\d\d-\d\d)-', b)
        if not md:
            continue
        d = date.fromisoformat(md.group(1))
        # numbered tracks: ...-t7s3, -track41s0, -tq-t8s2, -track57_202509s9,
        # and suffixed ones like -track64xxxs2, -track67ws1
        m = re.search(r'(?:^|-)t(?:rack)?(?:q-t)?(\d+(?:_\d+)?)[a-z]*s(\d+)', b)
        if m:
            out.append((m.group(1), int(m.group(2)), d, True))
            continue
        # named tracks appear either via a chord filename (-chord-med2023s14-) or plainly
        # (-med2023s25.gpx, -tosantorini2024s54.gpx). Both forms must be read.
        m = (re.search(r'-chord\d*-([a-z0-9]+?)s(\d+)', b)
             or re.search(r'-([a-z][a-z0-9]*?)s(\d+)(?:-[a-z0-9]+)?\.gpx$', b))
        if m and not m.group(1).startswith('track'):
            out.append((m.group(1), int(m.group(2)), d, False))
    return out

def _from_filenames():
    numbered, named = {}, {}
    for k, si, d, is_num in parse_export_names():
        (numbered if is_num else named).setdefault(k, []).append(d)
    return numbered, named

_cache = None
def ranges():
    """{normalised track key: (first_date, last_date)}, padded."""
    global _cache
    if _cache is not None:
        return _cache
    numbered, named = _from_filenames()
    out = {}
    for k, ds in list(numbered.items()) + list(named.items()):
        out[k] = (min(ds), max(ds))
    # A track ran from when the previous one ended until the next one began, so extend each
    # range out to its numbered neighbours. Without this, a track whose exported segments are
    # clustered gets an absurdly narrow range - Track 7 has 75 segments but only 4 dated, all
    # in one month, and was being bounded to 12 days when it actually runs into the next year.
    # Widening is the safe direction here: a wider window admits more journey lines to compare
    # against, so it under-reports missing track rather than inventing it.
    plain = sorted((int(k), k) for k in numbered if k.isdigit())
    for i, (n, k) in enumerate(plain):
        lo, hi = out[k]
        if i > 0:
            lo = min(lo, out[plain[i-1][1]][1])
        if i+1 < len(plain):
            hi = max(hi, out[plain[i+1][1]][0])
        out[k] = (lo, hi)
        # tracks with no exports at all sit between their numbered neighbours
        for missing in range(n+1, plain[i+1][0] if i+1 < len(plain) else n+1):
            out.setdefault(str(missing), (out[k][1], out[plain[i+1][1]][0]))
    _cache = {k: (v[0]-timedelta(days=PAD_DAYS), v[1]+timedelta(days=PAD_DAYS))
              for k, v in out.items()}
    return _cache

def segment_ranges():
    """{(track key, segment index): earliest date} for every segment named in nfl-export/."""
    global _segcache
    if _segcache is not None:
        return _segcache
    out = {}
    for k, si, d, _is_num in parse_export_names():
        key = (k, si)
        out[key] = min(out[key], d) if key in out else d
    _segcache = out
    return out

_segcache = None

def segment_window(track_name, seg_index, pad_days=4):
    """Narrow date bounds for one segment, by interpolating within its own track.

    Segment indices are ordered in time just as track numbers are, and `nfl-export/` dates a
    good fraction of them — 19 of Track 4's, for instance. So an undated segment can be
    bracketed by the nearest dated segments on either side of it *within the same track*,
    which is far tighter than the whole track's range. Falls back to the track range, and then
    to None, when there is nothing to interpolate between.
    """
    key = _norm(track_name)
    segs = {si: d for (k, si), d in segment_ranges().items() if k == key}
    if thinly_dated(track_name):
        # Nothing to interpolate *between*, and no year in the name to fall back on. Say so.
        # `Track 1` is why: 182 segments across nine crop files, spanning the whole 2022
        # delivery and into 2023, with exactly one dated by an export — from which every
        # segment inherited the fortnight 2023-05-27 .. 06-07. The 268 nm Biscay crossing,
        # a 2022-09 leg that is on the journey, was then compared against a fortnight of
        # 2023 lines and reported 100% missing. A fabricated window is worse than none:
        # callers can widen to the whole journey, but they cannot tell a guess from a fact.
        return None
    lo = hi = None
    if segs:
        below = [si for si in segs if si <= seg_index]
        above = [si for si in segs if si >= seg_index]
        if below:
            lo = segs[max(below)]
        if above:
            hi = segs[min(above)]
    tr = fallback_range(track_name)
    if lo is None:
        lo = tr[0] if tr else None
    if hi is None:
        hi = tr[1] if tr else None
    if lo is None or hi is None:
        return None
    if hi < lo:
        lo, hi = hi, lo
    return (lo-timedelta(days=pad_days), hi+timedelta(days=pad_days))

def thinly_dated(track_name):
    """Too few dated segments to say anything, and no year in the name to fall back on.

    `nfl-export/` dates a segment only when that segment was uploaded, so a long track can
    have one dated segment out of hundreds. Interpolating from a single point is not
    interpolation — it pins every segment of the track to that one date's neighbourhood.
    """
    key = _norm(track_name)
    n = sum(1 for k, _si in segment_ranges() if k == key)
    return n < MIN_DATED_TO_INTERPOLATE and not _named_year(track_name)

def fallback_range(track_name):
    """The range to fall back on where interpolation has nothing on one side.

    **For a named track the year in the name wins** over the range derived from
    `nfl-export/` filenames. `Med 2023` and `ToSantorini2024` are whole seasons with only a
    handful of exported segments, so that derived range bounds the *exports*, not the track
    — and a segment past the last exported one then inherits an upper bound months too
    early. Measured, not hypothetical: `Med 2023` s94, s98 and s101 end at the journey's own
    2023-11-24, 11-27 and 11-30 fixes, and every one of them was being bracketed to October.

    `overlaps()` always chose this way round; `segment_window()` chose the other, and the
    two disagreeing is what the bug was. One function now, used by both.
    """
    key = _norm(track_name)
    if not key.isdigit() and '_' not in key:
        return _named_year(track_name) or ranges().get(key)
    return ranges().get(key)

def _named_year(track_name):
    """A name like 'Med 2023' or 'ToSantorini2024' states its year; use the whole year."""
    m = re.search(r'(20\d\d)', track_name)
    if not m:
        return None
    y = int(m.group(1))
    return (date(y, 1, 1), date(y, 12, 31))

def overlaps(track_name, lo_date, hi_date):
    """Could this track have been recorded within [lo_date, hi_date]?

    Unknown tracks return True: this filter exists to drop candidates that are provably from
    another season, not to assert knowledge the map does not have.
    """
    if thinly_dated(track_name):
        # One dated segment out of 182 does not make a track "provably from another
        # season", and this filter exists for nothing else. `Track 1` answered False for
        # the whole of 2022 on that evidence, so the 2022 delivery was dropped before its
        # coverage was ever measured and the scan reported "0 source segments".
        return True
    r = fallback_range(track_name)
    if not r:
        return True
    lo = date.fromisoformat(lo_date) if isinstance(lo_date, str) else lo_date
    hi = date.fromisoformat(hi_date) if isinstance(hi_date, str) else hi_date
    return not (r[1] < lo or r[0] > hi)

if __name__ == '__main__':
    r = ranges()
    print(f'{len(r)} tracks dated\n')
    def sk(k):
        p = k.split('_')[0]
        return (0, int(p)) if p.isdigit() else (1, k)
    for k in sorted(r, key=sk):
        print(f'   {k:14s} {r[k][0]} .. {r[k][1]}')
