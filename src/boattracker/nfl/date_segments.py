"""The plotter segment ledger: which day each Raymarine segment was recorded, written down.

The chartplotter keeps the best positions and no time at all, so every tool here has had to
work out afresh which segment belongs to which day. The answer was never kept, except as
the dates in `nfl-export/` file names, and those were sometimes wrong: Track 52 s1, the
2025-08-28 approach to Istanbul, was filed under 08-29 because a phone fix at the shared
anchorage matched it there. This module writes the answer down, in
`<journey>/plotter-segments.tsv`, one row per segment, and says what dated each one.

Sources, strongest first:

* **phone**: the Organic Maps track matched along the segment by `timestamp_segments`,
  which tests order (Kendall's tau) as well as distance, so a revisit to the same water does
  not match. Gives the times of the first and last matched point too.
* **photo**: geotagged photographs matched the same way.
* **fix**: exactly one journey fix at the segment's last point within its date window. Two
  mean the boat came back there, and then the fix cannot tell which visit this was.
* **diary**: exactly one diary heading in the window that names the place nearest the
  segment's end, by `PLACES.md`.
* **export**: the date in an `nfl-export/` file name for this segment. A seed, not a check.
* **order**: nothing above, but the dated segments either side are of one day. The
  plotter's counter only goes up, so this one is of that day too.

The window is `track_dates.segment_window`, interpolated from the export names; with none,
only the phone and photographs are tried, and their order test has to carry it.

**The ledger is the owner's as much as the tool's.** A row whose `dated_by` is `owner` is
never rewritten, and the `notes` column is kept on every row. Owner rows also take part in
the plotter-order test, so a neighbour that contradicts one is cleared and dated again
between them; an owner row with no date (GPS spoofing, say) stays undated. Anything the tool doubts goes
in `check`: a source that disagrees with the one taken, an ambiguous fix, a date out of
plotter order.

    python3 -m boattracker.nfl.date_segments                # what would change
    python3 -m boattracker.nfl.date_segments --write        # into the ledger
"""

from __future__ import annotations

import argparse
import csv
import glob
import os
import re
import sys
import zoneinfo
from dataclasses import asdict, dataclass, field, fields, replace
from datetime import UTC, date, datetime, timedelta

from boattracker import config
from boattracker.geo import hav
from boattracker.nfl import omaps_export, timestamp_segments, track_dates
from boattracker.nfl.omaps_export import Fix
from boattracker.nfl.timestamp_segments import Segment
from boattracker.places import read_places, zone_at

FIX_M = 100          # a journey fix this close to the segment's last point ends it
PLACE_M = 1000       # the place nearest the segment's end, within this, names it
MAX_KN = 12          # a phone match implying more is a wrong window, not a fast boat


@dataclass
class Row:
    track: str
    seg: int
    guid: str = ''
    file: str = ''
    points: int = 0
    nm: float = 0.0
    start: str = ''     # lat,lon of the first point
    end: str = ''       # lat,lon of the last point
    date: str = ''      # local day: of the segment's end, or of its last timed point (t1)
    t0: str = ''        # UTC time of point i0, where a timed source pins one
    i0: int | str = ''
    t1: str = ''
    i1: int | str = ''
    dated_by: str = ''  # phone, photo, fix, diary, export, order - or owner, never rewritten
    check: str = ''     # what the tool doubts
    notes: str = ''     # the owner's; kept on every rerun

    @property
    def key(self) -> tuple[str, int]:
        return (self.track, self.seg)


COLUMNS = [f.name for f in fields(Row)]


@dataclass
class Sources:
    phone: list[Fix] = field(default_factory=list)
    photos: list[Fix] = field(default_factory=list)
    fixes: list[tuple[float, float, float]] = field(default_factory=list)  # lat, lon, epoch s
    heads: list[tuple[str, list[str]]] = field(default_factory=list)       # (day, place names)
    places: list[tuple[str, float, float]] = field(default_factory=list)
    export_date: date | None = None


def _clean(v) -> str:
    return re.sub(r'\s+', ' ', str(v)).strip()


def read_ledger(path) -> dict[tuple[str, int], Row]:
    if not os.path.exists(path):
        return {}
    out = {}
    with open(path, newline='') as f:
        for r in csv.DictReader(f, delimiter='\t'):
            kw: dict = {c: r.get(c, '') or '' for c in COLUMNS}
            kw['seg'] = int(kw['seg'])
            kw['points'] = int(kw['points'] or 0)
            kw['nm'] = float(kw['nm'] or 0)
            for c in ('i0', 'i1'):
                kw[c] = int(kw[c]) if kw[c] != '' else ''
            row = Row(**kw)
            out[row.key] = row
    return out


def write_ledger(path, rows: dict[tuple[str, int], Row]) -> None:
    with open(path, 'w', newline='') as f:
        w = csv.writer(f, delimiter='\t', lineterminator='\n')
        w.writerow(COLUMNS)
        for r in sorted(rows.values(), key=order_key):
            w.writerow([_clean(v) for v in asdict(r).values()])


def merge(old: dict, new: dict) -> dict:
    """The new proposals over the old ledger: owner rows and every note survive."""
    out = dict(old)
    for k, r in new.items():
        o = old.get(k)
        if o and o.dated_by == 'owner':
            continue
        if o:
            r.notes = o.notes
        out[k] = r
    return out


def order_key(s) -> tuple:
    """Plotter order: the track counter, then the segment index. Named tracks go first."""
    track = s.track
    idx = s.idx if hasattr(s, 'idx') else s.seg
    m = re.match(r'Track\s+(\d+)', track)
    return (1, int(m.group(1)), track, idx) if m else (0, 0, track, idx)


def dedupe(found: list[tuple[str, Segment]]) -> list[tuple[str, Segment]]:
    """One copy of each segment: the plotter exports overlap, and later ones run longer."""
    best: dict[tuple[str, int], tuple[str, Segment]] = {}
    for f, s in found:
        k = (s.track, s.idx)
        if k not in best or len(s.points) > len(best[k][1].points):
            best[k] = (f, s)
    return sorted(best.values(), key=lambda fs: order_key(fs[1]))


def _local_day(t: datetime, pos) -> str:
    z = zone_at(*pos) or 'UTC'
    return t.astimezone(zoneinfo.ZoneInfo(z)).strftime('%Y-%m-%d')


def _bounds(window, pos) -> tuple[datetime, datetime] | tuple[None, None]:
    """The window's local days at `pos` as UTC instants: midnight to midnight there."""
    if not window:
        return None, None
    z = zoneinfo.ZoneInfo(zone_at(*pos) or 'UTC')
    return (datetime.combine(window[0], datetime.min.time(), z).astimezone(UTC),
            datetime.combine(window[1] + timedelta(days=1), datetime.min.time(), z).astimezone(UTC))


CLUSTER_GAP = timedelta(hours=6)


def _timed(s: Segment, fixes: list[Fix], window, min_anchors: int = 3, **kw):
    lo, hi = _bounds(window, s.points[-1])
    m = timestamp_segments.match(s, fixes, lo=lo, hi=hi, min_anchors=min_anchors, **kw)
    if m is None:
        return None
    # the order test lets a revisit days later extend the match: one visit is one cluster
    clusters = [[m.anchors[0]]]
    for a in m.anchors[1:]:
        if a.t - clusters[-1][-1].t > CLUSTER_GAP:
            clusters.append([])
        clusters[-1].append(a)
    best = max(clusters, key=len)
    if len(best) < min(min_anchors, 2) or best[-1].t <= best[0].t:
        return None
    m = timestamp_segments.Match(s, best, m.tau)
    if m.hours > 0 and m.knots > MAX_KN:
        return None
    return m


def propose(s: Segment, src: Sources, window) -> Row:
    """One ledger row for a segment, from the strongest source that dates it."""
    first, last = s.points[0], s.points[-1]
    row = Row(s.track, s.idx, s.guid, '', len(s.points), round(s.nm, 2),
              f'{first[0]:.5f},{first[1]:.5f}', f'{last[0]:.5f},{last[1]:.5f}')
    found: list[tuple[str, str]] = []   # (source, day) for every source that dated it

    for name, pool, kw in (('phone', src.phone, {}),
                           ('photo', src.photos, {'min_anchors': 2})):
        m = _timed(s, pool, window, **kw) if pool else None
        if m:
            day = _local_day(m.t1, s.points[m.anchors[-1].i])
            found.append((name, day))
            if not row.dated_by:
                row.date, row.dated_by = day, name
                row.t0, row.i0 = m.t0.strftime('%Y-%m-%dT%H:%M:%SZ'), m.anchors[0].i
                row.t1, row.i1 = m.t1.strftime('%Y-%m-%dT%H:%M:%SZ'), m.anchors[-1].i

    lo, hi = _bounds(window, last)
    if window and lo and hi:
        at_end = [f for f in src.fixes if hav(f[:2], last) <= FIX_M
                  and lo.timestamp() <= f[2] < hi.timestamp()]
        if len(at_end) == 1:
            found.append(('fix', _local_day(datetime.fromtimestamp(at_end[0][2], UTC), last)))
        elif len(at_end) > 1:
            row.check = _add(row.check, f'{len(at_end)} fixes at the end in the window')

        near = min(((hav(last, p[1:]), p[0]) for p in src.places), default=(9e9, ''))
        if near[0] <= PLACE_M:
            days = sorted({d for d, names in src.heads
                           if window[0].isoformat() <= d <= window[1].isoformat()
                           and any(_same_place(near[1], n) for n in names)})
            if len(days) == 1:
                found.append(('diary', days[0]))
            elif len(days) > 1:
                row.check = _add(row.check, f'diary names {near[1]} on {len(days)} days')

    if src.export_date:
        found.append(('export', src.export_date.isoformat()))

    if not row.dated_by and found:
        row.dated_by, row.date = found[0]
    for name, day in found:
        if day != row.date:
            row.check = _add(row.check, f'{name} {day}')
    return row


def _same_place(place: str, heading_name: str) -> bool:
    """A PLACES.md name and a diary heading's name for the same spot, loosely."""
    a, b = place.lower(), heading_name.lower()
    return a in b or b in a or a.split(',')[0].strip() == b.split(',')[0].strip()


def _add(text: str, more: str) -> str:
    return f'{text}; {more}' if text else more


def check_order(rows: list[Row]) -> None:
    """Flag a date earlier than one already seen in plotter order: one of the two is wrong."""
    seen = ''
    for r in rows:
        if not r.date:
            continue
        if seen and r.date < seen:
            r.check = _add(r.check, f'out of order (after {seen})')
        seen = max(seen, r.date)


WEIGHT = {'owner': 1000, 'phone': 5, 'photo': 4, 'fix': 3, 'diary': 2, 'export': 1, 'order': 1}


def _weight(r: Row) -> float:
    # a short segment in water the boat keeps returning to matches other days as easily
    w = WEIGHT.get(r.dated_by, 0)
    return min(w, 2) if r.dated_by in ('phone', 'photo') and r.nm < 1 else w


def keep_ordered(rows: list[Row]) -> None:
    """Keep the heaviest chain of dates that runs in plotter order; clear the rest.

    The plotter's counter only goes up, so its segments are in time order. A date that
    breaks the order is wrong, or its neighbours are, and the heavier sources decide which:
    a phone match outweighs an export name, and the owner outweighs everything.
    """
    dated = [r for r in rows if r.date]
    best: list[float] = []
    prev: list[int] = []
    for i, r in enumerate(dated):
        b, p = 0.0, -1
        for j in range(i):
            if dated[j].date <= r.date and best[j] > b:
                b, p = best[j], j
        best.append(b + _weight(r))
        prev.append(p)
    keep, i = set(), max(range(len(dated)), key=lambda k: best[k], default=-1)
    while i >= 0:
        keep.add(id(dated[i]))
        i = prev[i]
    for r in dated:
        if id(r) not in keep and r.dated_by != 'owner':
            r.check = _add(r.check, f'{r.date} by {r.dated_by}, out of plotter order')
            r.date = r.dated_by = r.t0 = r.t1 = ''
            r.i0 = r.i1 = ''


def diary_heads(paths) -> list[tuple[str, list[str]]]:
    out = []
    for p in paths:
        with open(p) as f:
            for line in f:
                m = re.match(r'## \w+ (\d{4}-\d\d-\d\d) - (.*)', line)
                if m:
                    out.append((m.group(1), [n.strip() for n in m.group(2).split(' - ')]))
    return out


def load_sources(phone_paths, photos_dir, journey_path, places_path) -> Sources:
    phone = sorted(f for p in phone_paths for f in omaps_export.load(p, max_year=None))
    photos = []
    if photos_dir:
        from boattracker.nfl import time_and_positions as tp
        photos = sorted(Fix(p.lat, p.lon, datetime.fromtimestamp(p.t, UTC)) for p in tp.photo_points(photos_dir))
    fixes = []
    if journey_path and os.path.exists(journey_path):
        from boattracker.nfl import time_and_positions as tp
        fixes = tp.Journey(journey_path).fixes()
    places = read_places(places_path)[0] if os.path.exists(places_path) else []
    heads = diary_heads(sorted(glob.glob(config.DIARY_GLOB)))
    return Sources(phone, photos, fixes, heads, places)


def build(found: list[tuple[str, Segment]], src: Sources,
          old: dict[tuple[str, int], Row] | None = None) -> dict[tuple[str, int], Row]:
    """A row per segment. The `old` ledger's owner rows stand as they are, and take part in
    the plotter-order test, so they clear and bound their neighbours too."""
    old = old or {}
    exports = track_dates.segment_ranges()
    rows = []
    by_key: dict[tuple[str, int], tuple[str, Segment]] = {}
    for f, s in found:
        if len(s.points) < 2:
            continue
        one = Sources(src.phone, src.photos, src.fixes, src.heads, src.places,
                      exports.get((track_dates._norm(s.track), s.idx)))
        r = propose(s, one, track_dates.segment_window(s.track, s.idx))
        o = old.get(r.key)
        if o and o.dated_by == 'owner':
            r = replace(o, guid=r.guid, points=r.points, nm=r.nm, start=r.start, end=r.end)
        r.file = os.path.basename(f)
        rows.append(r)
        by_key[r.key] = (f, s)
    for chain in _chains(rows):
        keep_ordered(chain)
        # what was cleared, or never dated, is tried again between its kept neighbours
        for k, r in enumerate(chain):
            if r.date or r.dated_by == 'owner':
                continue
            lo = next((x.date for x in reversed(chain[:k]) if x.date), None)
            hi = next((x.date for x in chain[k+1:] if x.date), None)
            if not (lo and hi):
                continue
            f, s = by_key[r.key]
            again = propose(s, Sources(src.phone, src.photos, src.fixes, src.heads, src.places),
                            (date.fromisoformat(lo), date.fromisoformat(hi)))
            if again.date and lo <= again.date <= hi:
                again.file, again.check = r.file, _add(r.check, again.check)
                chain[k] = again
            elif lo == hi:
                # the plotter's counter only goes up: between two of one day is that day
                chain[k] = replace(r, date=lo, dated_by='order')
        keep_ordered(chain)
        check_order(chain)
        rows = [x for x in rows if x.key not in {c.key for c in chain}] + chain
    return {r.key: r for r in rows}


def _chains(rows: list[Row]) -> list[list[Row]]:
    """The numbered tracks are one counter, so one chain; each named track is its own."""
    numbered = [r for r in rows if order_key(r)[0] == 1]
    named = sorted({r.track for r in rows if order_key(r)[0] == 0})
    return [sorted(numbered, key=order_key)] + [
        sorted((r for r in rows if r.track == t), key=order_key) for t in named]


def main(argv: list[str] | None = None) -> None:
    from boattracker.nfl import import_phone_export
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--corpus', action='append',
                    help='a plotter GPX (default: every Tracks*.gpx in <data>)')
    ap.add_argument('--tracks', help='comma-separated track names, e.g. "Track 52,Track 53"')
    ap.add_argument('--ledger', default=os.path.join(config.JOURNEY, 'plotter-segments.tsv'))
    ap.add_argument('--write', action='store_true')
    a = ap.parse_args(argv)
    corpus = a.corpus or sorted(glob.glob(os.path.join(config.DATA, 'Tracks*.gpx')))
    tracks = [t.strip() for t in a.tracks.split(',')] if a.tracks else None
    found = dedupe([(f, s) for f in corpus for s in timestamp_segments.load_segments(f, tracks)])
    found = [(f, s) for f, s in found
             if s in timestamp_segments.drop_off_planet([s for _, s in found])[0]]
    phone_paths = sorted(glob.glob(os.path.join(import_phone_export.phone_dir(), '*.km[lz]')))
    src = load_sources(phone_paths, config.get('PHOTOS', None),
                       os.path.join(config.JOURNEY, 'journey-snapshot.json'),
                       os.path.join(config.JOURNEY, 'PLACES.md'))
    old = read_ledger(a.ledger)
    new = merge(old, build(found, src, old))
    changed = [k for k in new if k not in old or asdict(new[k]) != asdict(old[k])]
    by = {}
    for r in new.values():
        by[r.dated_by or 'undated'] = by.get(r.dated_by or 'undated', 0) + 1
    print(f'{len(new)} segments, {len(changed)} changed; dated by ' +
          ', '.join(f'{k} {v}' for k, v in sorted(by.items())), file=sys.stderr)
    for k in sorted(changed, key=lambda k: order_key(new[k])):
        r, o = new[k], old.get(k)
        was = f' (was {o.date or "-"} by {o.dated_by or "-"})' if o else ''
        print(f'{r.track} s{r.seg}: {r.date or "-"} by {r.dated_by or "-"}{was}'
              + (f'  [{r.check}]' if r.check else ''))
    if a.write:
        write_ledger(a.ledger, new)
        print(f'written to {a.ledger}', file=sys.stderr)


if __name__ == '__main__':
    main()
