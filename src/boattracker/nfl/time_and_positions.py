"""'Time and positions' sections for diary passage days, from every timed source there is.

The tracker's own stop detection (`boattracker.tracker.point`, which wrote the old
stops.log lines) stopped running in February 2025. This reconstructs the same kind of
lines from:

* the Organic Maps phone tracks (`<data>/../phone/`, see `import_phone_export`), exact to
  the second but recording a person: kept only within ~500 m of the boat's own geometry
  and below 15 kts;
* the noforeignland journey snapshot (`<journey>/journey-snapshot.json`). Only tracker
  (`GPX Export`) and app lines carry real vertex times; Raymarine and Manual lines had
  their inner times interpolated along distance, which erases stays, so only their fixes
  count;
* GPS-tagged photographs whose fix clock agrees with the shutter, minus those flagged
  ashore or dropped in `manual-locations.json` (SOURCES.md, "Photograph positions").

Raymarine point counts cannot time a passage: under way the distance trigger fires, so
they measure distance (RAYMARINE-GPX.md, "Sampling interval"). Where only fixes are timed,
a departure is known to lie between two of them; it is clamped to the diary day whose
heading names the passage, and a 7 kts ceiling bounds the rest. Hence "+/-" and "A .. B".

Each day takes its legs from the phone when the phone ran all day, and from the journey
otherwise; **a journey leg that the phone recorded more precisely is re-timed by it**, so a
phone that ran for the morning's move but was off for the afternoon's no longer costs the
morning its minute-exact times.

Every time written is UTC. A local zone is used for one thing only: deciding which diary
day a moment belongs to, since the diary is written by the local clock. It comes from the
boat's position (`tzfpy`, the timezone-boundary-builder polygons), taken from the nearest
position inside territorial waters — offshore the data has only the nautical zones, which
keep no summer time.

    python3 -m boattracker.nfl.time_and_positions DIARY FROM TO           # draft to stdout
    python3 -m boattracker.nfl.time_and_positions DIARY FROM TO --write   # into the diary

A rerun replaces the sections this tool wrote for days in FROM..TO. Sections without its
marker in their note are hand-maintained, and their days are left alone.
"""

from __future__ import annotations

import argparse
import bisect
import contextlib
import datetime as D
import glob
import json
import math
import os
import re
import sys
import zoneinfo
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from typing import NamedTuple

from boattracker import config
from boattracker.geo import NM, hav
from boattracker.nfl import exif_index, import_phone_export, omaps_export

UTC = D.UTC
MARKER = 'boattracker.nfl.time_and_positions'
## Sections written while this lived in the journey record carry its old path; a rerun
## must recognise them, or it would take them for hand-maintained and never replace them.
MARKERS = (MARKER, 'journey/archive/time_and_positions.py')
SOURCE_NAMES = {'phone': 'the Organic Maps phone track', 'nfl': 'the noforeignland journey',
                'photo': 'photograph geotags'}
LatLon = tuple[float, float]
Sections = dict[str, tuple[list[str], list[str]]]  # day -> (sources, lines)
MAX_KTS = 7  # nothing here sails faster than this on average; it bounds an untimed passage
DAY_RE = re.compile(r'## \w+ (\d{4}-\d\d-\d\d)')


class Pt(NamedTuple):
    """A position whose true time lies in [lo, hi]; `t` is the best guess inside it.

    `stop` is False, True (a fix that may hide a stay) or 2 (the owner placed the boat
    here, so it stopped however brief the record).
    """
    t: float
    lat: float
    lon: float
    src: str
    lo: float
    hi: float
    stop: bool | int = False


@dataclass
class Leg:
    """One move: departure in [dep_lo, dep_hi] from `a`, arrival in [arr_lo, arr_hi] at `b`."""
    dep_lo: float
    dep_hi: float
    arr_lo: float
    arr_hi: float
    a: tuple[float, float]
    b: tuple[float, float]
    src: str = 'nfl'
    dist: float = 0.0  # sailed, metres
    tmin: float = 0.0  # shortest and longest the move can have taken, seconds
    tmax: float = 0.0
    srcs: set[str] = field(default_factory=set)  # every source among its points

    @property
    def width(self) -> float:
        """How vague the leg is: the wider of its two windows."""
        return max(self.dep_hi - self.dep_lo, self.arr_hi - self.arr_lo)

    @property
    def line(self) -> float:
        return hav(self.a, self.b)


def _seg_dist(p: tuple, a: tuple, b: tuple) -> tuple[float, tuple[float, float]]:
    """Distance in metres from p to segment a-b, and the nearest point on it (lat, lon)."""
    kx = math.cos(math.radians(a[0])) * 111320
    ax, ay, bx, by = a[1]*kx, a[0]*110540, b[1]*kx, b[0]*110540
    px, py = p[1]*kx, p[0]*110540
    dx, dy = bx-ax, by-ay
    f = max(0.0, min(1.0, ((px-ax)*dx + (py-ay)*dy) / ((dx*dx + dy*dy) or 1)))
    q = (a[0] + (b[0]-a[0])*f, a[1] + (b[1]-a[1])*f)
    return hav(p, q), q


def _cell(lat: float, lon: float) -> tuple[int, int]:
    return (round(lat*200), round(lon*200))  # ~500 m cells


class Journey:
    """The journey snapshot: dated points, and the grid of cells the boat's geometry covers."""

    def __init__(self, path: str):
        with open(path) as f:
            self.data = json.load(f)
        self.grid: set[tuple[int, int]] = set()
        self.anchored: set[float] = set()  # photograph times that dated a journey vertex

    def near(self, lat: float, lon: float) -> bool:
        a, b = _cell(lat, lon)
        return any((a+i, b+j) in self.grid for i in (-1, 0, 1) for j in (-1, 0, 1))

    def points(self, anchors: Iterable[Pt] = ()) -> list[Pt]:
        """Every vertex, untimed ones interpolated between their timed neighbours.

        `anchors` are real timed points (photographs): one within 150 m of an untimed
        vertex gives that vertex its time, so the plotter geometry is dated by the
        photographs rather than by distance alone. Also fills the grid."""
        d = self.data
        src = {f['properties']['fixId']: f['properties'].get('source')
               for f in d['geojson']['features'] if f['geometry']['type'] == 'Point'}
        lines = []
        for f in d['geojson']['features']:
            if f['geometry']['type'] != 'LineString':
                continue
            c = f['geometry']['coordinates']
            if not (len(c[0]) > 2 and c[0][2]):
                continue
            # only the tracker and the app stamp vertices as they record them; Raymarine and
            # Manual lines got their inner times interpolated along distance, which erases stays
            real = src.get(f['properties']['fixId']) in ('GPX Export', 'NFL App')
            vs = []
            for k, v in enumerate(c):
                self.grid.add(_cell(v[1], v[0]))
                t = v[2]/1000 if len(v) > 2 and v[2] and (real or k in (0, len(c)-1)) else None
                vs.append([(t,) if t else (), v[1], v[0]])
            lines.append(vs)
        anchors = sorted(anchors)
        times = [a[0] for a in anchors]
        self.anchored.update(times)
        out = []
        for vs in sorted(lines, key=lambda vs: vs[0][0][0]):
            a = 0
            while True:
                nxt = [k for k in range(a+1, len(vs)) if vs[k][0]]
                if not nxt:
                    break
                b = nxt[0]
                ta, tb = vs[a][0][-1], vs[b][0][0]
                # anchors inside this span, kept only while they advance along the line
                last = a
                for x in anchors[bisect.bisect_right(times, ta):bisect.bisect_left(times, tb)]:
                    dist, k = min((hav(x[1:3], vs[k][1:3]), k) for k in range(last, b+1))
                    if dist < 150:
                        # at the end vertex this is the boat already there, before the fix
                        vs[k][0] = tuple(sorted(vs[k][0] + (x[0],)))
                        last = k
                        continue
                    # between two vertices: the plotter lays points by distance, so a
                    # photograph under way often falls on the line rather than at a vertex
                    best = min(((_seg_dist(x[1:3], vs[k][1:3], vs[k+1][1:3]), k)
                                for k in range(last, b)), default=((9e9, None), None))
                    if best[0][0] < 150:
                        k, q = best[1], best[0][1]
                        vs.insert(k+1, [(x[0],), q[0], q[1]])
                        b += 1
                        last = k+1
                a = b
            # every vertex now carries zero or more real times; interpolate the rest
            flat = []
            for k, v in enumerate(vs):
                for t in (v[0] or (None,)):
                    flat.append((t, v[1], v[2], k))
            idx = [k for k, v in enumerate(flat) if v[0]]
            for a, b in zip(idx, [*idx[1:], None], strict=True):
                ta = flat[a][0]
                if b is None:
                    out.append(Pt(ta, flat[a][1], flat[a][2], 'nfl', ta, ta, flat[a][3] == 0))
                    continue
                tb = flat[b][0]
                seg = flat[a:b+1]
                dist = [0.0]
                for x in range(len(seg)-1):
                    dist.append(dist[-1] + hav(seg[x][1:3], seg[x+1][1:3]))
                for k, v in enumerate(seg[:-1]):
                    if k == 0:
                        # a fix is an arrival; with a long untimed span after it, a stay hides there
                        near_start = hav(v[1:3], flat[0][1:3]) < 300
                        out.append(Pt(ta, v[1], v[2], 'nfl', ta, ta, near_start and tb - ta >= 3600))
                    else:
                        t = ta + (tb-ta)*dist[k]/(dist[-1] or 1)
                        out.append(Pt(t, v[1], v[2], 'nfl', ta, tb, False))
        return out

    def fixes(self) -> list[tuple[float, float, float]]:
        """Every fix as (lat, lon, epoch seconds)."""
        return [(f['geometry']['coordinates'][1], f['geometry']['coordinates'][0],
                 f['properties']['timeMs']/1000)
                for f in self.data['geojson']['features']
                if f['geometry']['type'] == 'Point' and f['properties'].get('timeMs')]

    def unheaded(self, diary_text: str, frm: str, to: str) -> list[str]:
        """Journey legs of 2 nm or more on days with no passage heading in the diary."""
        d = self.data
        pts = {f['properties']['fixId']: f for f in d['geojson']['features']
               if f['geometry']['type'] == 'Point'}
        pdays = set(re.findall(r'^## \w+ (\d{4}-\d\d-\d\d) - .* - ', diary_text, re.M))
        days = set(re.findall(r'^## \w+ (\d{4}-\d\d-\d\d)', diary_text, re.M))
        out = []
        for f in d['geojson']['features']:
            if f['geometry']['type'] != 'LineString':
                continue
            c = f['geometry']['coordinates']
            if not (len(c[0]) > 2 and c[0][2]):
                continue  # no times on this line; points() skips it too
            nm = sum(hav((c[i][1], c[i][0]), (c[i+1][1], c[i+1][0])) for i in range(len(c)-1)) / NM
            p = pts.get(f['properties']['fixId'])
            if not p or nm < 2:
                continue
            tz = zoneinfo.ZoneInfo(zone_at(c[-1][1], c[-1][0]) or 'UTC')
            t0 = D.datetime.fromtimestamp(c[0][2]/1000, tz)
            t1 = D.datetime.fromtimestamp(p['properties']['timeMs']/1000, tz)
            if not (frm <= t1.strftime('%Y-%m-%d') <= to):
                continue
            span_days = ({(t0 + D.timedelta(days=k)).strftime('%Y-%m-%d')
                          for k in range((t1-t0).days + 1)} | {t1.strftime('%Y-%m-%d')})
            if span_days & pdays:
                continue
            note = '' if t1.strftime('%Y-%m-%d') in days else ' (no diary entry that day)'
            out.append(f"* {t0:%Y-%m-%d %H:%M} .. {t1:%Y-%m-%d %H:%M} local: {nm:.1f}nm to "
                       f"{c[-1][1]:.5f},{c[-1][0]:.5f} [{p['properties'].get('source')}]{note}")
        return out


def phone_points(paths: Iterable[str]) -> list[Pt]:
    out = []
    for path in paths:
        for f in omaps_export.load(path, max_year=None):
            t = f.t.timestamp()
            out.append(Pt(t, f.lat, f.lon, 'phone', t, t, False))
    return out


def clocks_agree(shutter: float, gps: float) -> bool:
    """Whether a shutter clock, read as if it were UTC, and a GPS fix time agree.

    The shutter runs on whatever zone the phone's network gave it, which need not be where
    the phone was; the fix time is UTC. A fix from the moment of exposure differs from the
    shutter by a whole number of hours. A stale cached fix leaves minutes over.
    """
    diff = shutter - gps
    return abs(diff) <= 14*3600 and abs(diff - round(diff/3600)*3600) <= 600


def photo_points(photos: str) -> list[Pt]:
    """GPS-fixed photographs whose fix clock agrees with the shutter: exact to the second."""
    with open(f'{photos}/exif-index.json') as f:
        index = {r['path']: r for r in json.load(f)}
    manual = f'{photos}/manual-locations.json'
    with contextlib.redirect_stdout(sys.stderr):
        merged = exif_index.apply_manual(index, manual)
    # the owner saying where the boat lay makes it a stop, however brief the photographs;
    # only for that photograph: a day entry also covers the photographs taken under way
    placed = set()
    if os.path.exists(manual):
        with open(manual) as f:
            placed = {e['path'] for e in json.load(f) if e.get('path') and e.get('ashore') is False}
    out = []
    for x in merged.values():
        if x.get('ashore') or x.get('position_from') == 'dropped':
            continue
        # a coarse network fix is no use as a position, but one the owner has placed is
        coarse = ((x.get('fix') or '').lower() != 'gps'
                  and x.get('position_from') not in ('corrected', 'recalled'))
        if not (x.get('lat') and x.get('time') and x.get('gps_time')) or coarse:
            continue
        try:
            g = D.datetime.strptime(x['gps_time'], '%Y:%m:%d %H:%M:%SZ').replace(tzinfo=UTC).timestamp()
        except ValueError:
            continue
        shutter = D.datetime.fromisoformat(x['time']).replace(tzinfo=UTC).timestamp()
        if not clocks_agree(shutter, g):
            continue
        out.append(Pt(g, x['lat'], x['lon'], 'photo', g, g, 2 if x['path'] in placed else False))
    return out


## Reserved names in PLACES.md for spots that are not places: the owner's verdict that a
## "stop" there was slow sailing, or that a position there was the phone carried ashore.
AT_SEA = 'at sea'
ASHORE = 'ashore (not the boat)'


def read_places(path: str) -> tuple[list[tuple[str, float, float]], list[LatLon], list[LatLon]]:
    """(places, at_sea, ashore) from a PLACES.md table: named places as (name, lat, lon),
    and the positions of the two reserved names as (lat, lon)."""
    places, at_sea, ashore = [], [], []
    with open(path) as f:
        for line in f:
            m = re.match(r'\|\s*([^|]+?)\s*\|\s*(-?\d+\.\d+)\s*\|\s*(-?\d+\.\d+)\s*\|', line)
            if not m:
                continue
            name, pos = m.group(1), (float(m.group(2)), float(m.group(3)))
            if name == AT_SEA:
                at_sea.append(pos)
            elif name == ASHORE:
                ashore.append(pos)
            else:
                places.append((name, *pos))
    return places, at_sea, ashore


def not_ashore(pts: list[Pt], ashore: Iterable[LatLon], radius: float = 300) -> list[Pt]:
    """Without the points at a spot the owner placed on land: the phone without the boat."""
    return [p for p in pts if not any(hav(p[1:3], a) < radius for a in ashore)]


def zone_at(lat: float, lon: float) -> str | None:
    """The zone at a position, or None offshore, where only the nautical zones exist."""
    try:
        from tzfpy import get_tz
    except ImportError as e:
        raise SystemExit('the diary day needs tzfpy: pip install "boattracker[diary]"') from e
    z = get_tz(lon, lat)
    return None if not z or z.startswith('Etc/') else z


def day_zone(pts: list[Pt], t: float) -> str:
    """The zone the diary was written in around `t`: from the boat's nearest-in-time
    position that lies in some country's waters, else UTC."""
    for p in sorted(pts, key=lambda p: abs(p.t - t)):
        if abs(p.t - t) > 4*86400:
            break
        z = zone_at(p.lat, p.lon)
        if z:
            return z
    return 'UTC'


def day_window(day: str, zone: str) -> tuple[float, float]:
    """The UTC bounds of a diary day kept by the clock of `zone`."""
    tz = zoneinfo.ZoneInfo(zone)
    d = D.date.fromisoformat(day)
    start = D.datetime(d.year, d.month, d.day, tzinfo=tz)
    end = start.replace(tzinfo=None) + D.timedelta(days=1)
    return start.timestamp(), end.replace(tzinfo=tz).timestamp()


def _fmt(ts: float) -> str:
    return D.datetime.fromtimestamp(ts, UTC).strftime('%Y-%m-%dT%H%M')


def _hours(sec: float) -> str:
    h = sec/3600
    return f"{h:.0f} hours" if h >= 1.5 else f"{sec/60:.0f} minutes"


def _span(sec: float) -> str:
    return str(D.timedelta(seconds=int(round(sec/60)*60)))[:-3]


def _when(lo: float, hi: float) -> str:
    if hi - lo <= 900:
        return f"{_fmt((lo+hi)/2)} UTC"
    return f"{_fmt((lo+hi)/2)} UTC +/- {_hours((hi-lo)/2)}"


def stops(pts: list[Pt], radius: float = 300, min_stay: float = 1200,
          merge: float = 600) -> list[list]:
    """Index ranges (first, last, measured) where the track stays within radius for min_stay.

    Consecutive stops closer than `merge` metres are one stop: walks ashore, dinghy
    trips and anchor swinging all look like short moves that end where they began."""
    res, i, n = [], 0, len(pts)
    while i < n:
        j = centre = i
        while j+1 < n and hav(pts[centre][1:3], pts[j+1][1:3]) < radius:
            j += 1
            # measure from the first really timed point: an interpolated vertex may lie
            # hundreds of metres from where the boat actually stayed
            if pts[centre].lo != pts[centre].hi and pts[j].lo == pts[j].hi:
                centre = j
        timed = [p.t for p in pts[i:j+1] if p.lo == p.hi]
        measured = ((bool(timed) and timed[-1] - timed[0] >= min_stay)
                    or any(p.stop == 2 for p in pts[i:j+1]))
        if measured or any(p.stop for p in pts[i:j+1]):
            res.append([i, j, measured])
            i = j+1
        else:
            i += 1
    merged = []
    for r in res:
        if merged and hav(pts[merged[-1][0]][1:3], pts[r[0]][1:3]) < merge:
            merged[-1][1] = r[1]
            merged[-1][2] = merged[-1][2] or r[2]
        else:
            merged.append(r)
    return merged


def clean_phone(pts: list[Pt], near: Callable[[float, float], bool], maxkn: float = 15) -> list[Pt]:
    """The phone records a person: keep only points on the boat's geometry and at boat speeds."""
    out = []
    for p in pts:
        if not near(p.lat, p.lon):
            continue
        if out and p.t > out[-1].t:
            kn = hav(out[-1][1:3], p[1:3]) / (p.t-out[-1].t) * 3600 / NM
            if kn > maxkn:
                continue
        out.append(p)
    return out


def _path_len(pts: list[Pt], a: int, b: int) -> float:
    """Track length from a to b; photos date the track but are too sparse to trace it."""
    q = [p for p in pts[a:b+1] if p.src != 'photo'] or [pts[a], pts[b]]
    return sum(hav(q[x][1:3], q[x+1][1:3]) for x in range(len(q)-1))


def passages(pts: list[Pt], d0: float, d1: float, next_d0: float, at_sea: Iterable[LatLon] = (),
             radius: float = 400, fold: float = 2*3600, fold_slack: float = 24*3600,
             fixes: list[tuple[float, float, float]] | None = None, anchor_m: float = 500,
             anchor_days: float = 2) -> list[Leg]:
    """The legs departing within [d0, d1).

    A short stop within `radius` of an `at_sea` position is no stop: the owner has judged it
    slow sailing, so the legs either side of it are one. Short is a measured stay under
    `fold` seconds or, with no stay measured, room for under `fold_slack` of one between the
    neighbouring stops - a hole in the data mid-passage leaves hours, while a sound the boat
    lay in for days leaves days. The measured stay includes the approach inside the stop
    radius, so a crawl at half a knot already reads as forty minutes; hence hours rather
    than the thirty minutes a general offshore rule would use.

    With `fixes` - the journey's fixes as (lat, lon, t) - a stop counts only when one lies
    within `anchor_m` of it, within `anchor_days` of its time or as the latest fix before
    that (a long stay's arrival), and the leg reports the fix's
    position. The fixes are the owner's consolidated record of where the boat lay, derived
    from all the sources; the phone records a person, and a walk ashore is a stop with no
    fix near it."""
    if len(pts) < 2:
        return []
    st = stops(pts)
    # a fix in mid-passage looks like a stop; drop it unless a dwell was measured or the
    # times leave no room for the boat to have passed straight through
    k = 1
    while k < len(st) - 1:
        pa, pc = st[k-1][1], st[k+1][0]
        sailed = _path_len(pts, pa, pc)
        # the longest the boat can have stayed here, sailing the rest at full speed
        slack = pts[pc].hi - pts[pa].lo - sailed/NM/MAX_KTS*3600
        timed = [p.t for p in pts[st[k][0]:st[k][1]+1] if p.lo == p.hi]
        stay = timed[-1] - timed[0] if st[k][2] and timed else None
        offshore = any(hav(pts[st[k][0]][1:3], a) < radius or hav(pts[st[k][1]][1:3], a) < radius
                       for a in at_sea)
        if ((stay is None and slack < 2*3600)
                or (offshore and (stay < fold if stay is not None else slack < fold_slack))):
            del st[k]
            continue
        k += 1
    pos = [None] * len(st)
    if fixes is not None:
        fixes = sorted(fixes, key=lambda f: f[2])
        times = [f[2] for f in fixes]
        kept = []
        for s in st:
            lo, hi = pts[s[0]].lo - anchor_days*86400, pts[s[1]].hi + anchor_days*86400
            cands = fixes[bisect.bisect_left(times, lo):bisect.bisect_right(times, hi)]
            # a long stay has its fix at the arrival, maybe weeks before: the latest fix
            # before the stop began still says where the boat lay
            k = bisect.bisect_right(times, pts[s[0]].lo) - 1
            if k >= 0:
                cands = [fixes[k], *cands]
            near = [(hav(pts[i][1:3], f), f) for f in cands for i in (s[0], s[1])]
            best = min(near, default=(9e9, None), key=lambda x: x[0])
            if best[0] < anchor_m:
                kept.append((s, (best[1][0], best[1][1])))
        # two stops inside one anchorage can both lie within reach of its fix: one stop
        merged: list = []
        for s_, p_ in kept:
            if merged and merged[-1][1] == p_:
                merged[-1] = ([merged[-1][0][0], s_[1], merged[-1][0][2] or s_[2]], p_)
            else:
                merged.append((s_, p_))
        st, pos = [k[0] for k in merged], [k[1] for k in merged]
    out = []
    for k in range(1, len(st)):
        pa, pb = st[k-1][1], st[k][0]
        # a confirmed photograph is also snapped onto the line, so it may sit there twice;
        # the window runs to the next point that is not the same moment
        nx = pa + 1
        while nx < pb and pts[nx].hi <= pts[pa].t + 1:
            nx += 1
        dep_lo, dep_hi = pts[pa].lo, pts[nx].hi
        # a departure window reaching into the next passage day belongs to that day
        if dep_hi < d0 or dep_lo >= d1 or dep_hi >= next_d0:
            continue
        # the diary heading says the boat left on this day
        dep_lo, dep_hi = max(dep_lo, d0), min(dep_hi, d1)
        pv = pb - 1
        while pv > pa and pts[pv].lo >= pts[pb].t - 1:
            pv -= 1
        arr_lo, arr_hi = pts[pv].lo, pts[pb].hi
        dist = _path_len(pts, pa, pb)
        # from the departure, and from the point that sets the arrival window's lower bound:
        # after a folded stop that is where the boat left it, with the rest still to sail
        q = pv
        while q > pa and pts[q].t > pts[pv].lo + 1:
            q -= 1
        arr_lo = max(arr_lo, dep_lo + dist/NM/MAX_KTS*3600,
                     pts[pv].lo + _path_len(pts, q, pb)/NM/MAX_KTS*3600)
        src = pts[pa].src if pts[pa].src == 'phone' else 'nfl'
        if src == 'phone' and hav(pts[pa][1:3], pts[pb][1:3]) < NM/2:
            continue  # half a mile in the phone track is a dinghy trip as often as not
        tmin, tmax = max(arr_lo - dep_hi, dist/NM/MAX_KTS*3600, 60), arr_hi - dep_lo
        a, b = pos[k-1] or (pts[pa].lat, pts[pa].lon), pos[k] or (pts[pb].lat, pts[pb].lon)
        # the leg runs from fix to fix, so the way to and from the track counts as sailed
        dist += hav(a, pts[pa][1:3]) + hav(pts[pb][1:3], b)
        leg = Leg(dep_lo, dep_hi, arr_lo, arr_hi, a, b, src, dist, tmin, max(tmax, tmin))
        leg.srcs = {p.src for p in pts[pa:pb+1]}
        out.append(leg)
    return out


def retime_ends(legs: list[Leg], phone: list[Pt], match_m: float = 1000,
                gap: float = 1800) -> list[Leg]:
    """The journey's legs, each end narrowed to the phone's time where the phone saw the
    boat arrive at it, or leave it, inside that end's window.

    Finer than `retime`: the phone may have the evening's arrival but not the morning's
    departure. A phone stop that starts right after the phone was off (a gap over `gap`
    seconds) is the phone switching on, not an arrival; one that ends right before it went
    off is no departure either."""
    pts = sorted(phone)
    arrivals, departures = [], []
    for a, b, measured in stops(pts):
        if not measured:
            continue
        if a > 0 and pts[a].t - pts[a-1].t <= gap:
            arrivals.append((pts[a].t, pts[a][1:3]))
        if b + 1 < len(pts) and pts[b+1].t - pts[b].t <= gap:
            departures.append((pts[b].t, pts[b][1:3]))
    out = []
    for g in legs:
        arr = [t for t, p in arrivals if g.arr_lo <= t <= g.arr_hi and hav(p, g.b) <= match_m]
        dep = [t for t, p in departures if g.dep_lo <= t <= g.dep_hi and hav(p, g.a) <= match_m]
        if not arr and not dep:
            out.append(g)
            continue
        n = replace(g, srcs=g.srcs | {'phone'})
        least = g.dist/NM/MAX_KTS*3600  # the shortest the move can have taken
        if dep:
            n.dep_lo = n.dep_hi = max(dep)
            n.arr_lo = max(n.arr_lo, n.dep_hi + least)
        if arr:
            n.arr_lo = n.arr_hi = min(arr)
            n.dep_hi = min(n.dep_hi, n.arr_lo - least)
        if n.arr_lo > n.arr_hi or n.dep_lo > n.dep_hi:
            out.append(g)  # the phone's times do not fit this leg
            continue
        n.tmin = max(n.arr_lo - n.dep_hi, g.dist/NM/MAX_KTS*3600, 60)
        n.tmax = max(n.arr_hi - n.dep_lo, n.tmin)
        out.append(n)
    return out


def _worst(legs: list[Leg]) -> float:
    return max((g.width for g in legs), default=9e9)


def _walking(leg: Leg) -> bool:
    """A phone carried around ashore makes long "passages" slower than any sailing, or day-long ones."""
    v = leg.dist/NM/leg.tmin*3600
    return (v < 1.0 and leg.tmin > 2*3600) or leg.tmin > 24*3600


def retime(legs: list[Leg], phone: list[Leg], match_m: float = 1000,
           same_move: float = 3*3600) -> list[Leg]:
    """The journey's legs, each re-timed by the phone where the phone has the same move
    more precisely: both ends within `match_m`, less than `same_move` apart.

    Nothing is added or dropped. Mixing the two sources any more freely was tried: the
    journey's windows span hours, so legs from both overlap without being the same move,
    and merging the points zig-zags between interpolated and recorded times."""
    out = []
    for g in legs:
        same = [p for p in phone if hav(p.a, g.a) <= match_m and hav(p.b, g.b) <= match_m
                and p.dep_lo - g.arr_hi < same_move and g.dep_lo - p.arr_hi < same_move
                and p.width < g.width]
        out.append(min(same, key=lambda p: p.width) if same else g)
    return out


def render(leg: Leg, name_a: str, name_b: str) -> list[str]:
    dep = _when(leg.dep_lo, leg.dep_hi)
    if leg.tmax - leg.tmin <= 1800:
        mid = (leg.tmin + leg.tmax) / 2
        dur = f"moved for {_span(mid)}"
        spd = f"avg speed {leg.dist/NM/mid*3600:.1f} kts"
    else:
        dur = f"moved for {_span(leg.tmin)} .. {_span(leg.tmax)}"
        spd = (f"avg speed {leg.dist/NM/leg.tmax*3600:.1f} .. "
               f"{min(leg.dist/NM/leg.tmin*3600, 99):.1f} kts")
    return [f"* {dep}: departed from {leg.a[0]:.5f},{leg.a[1]:.5f} ({name_a})",
            f"* {dep}: {dur}, line distance {leg.line/NM:.1f}nm, "
            f"sailed distance {leg.dist/NM:.1f}nm, {spd}",
            f"* {_when(leg.arr_lo, leg.arr_hi)}: arrived at {leg.b[0]:.5f},{leg.b[1]:.5f} ({name_b})"]


def hand_maintained(text: str) -> set[str]:
    """Days whose Time and positions subsection carries none of this tool's markers."""
    done, day, lines = set(), None, text.split('\n')
    for i, line in enumerate(lines):
        m = DAY_RE.match(line)
        if m:
            day = m.group(1)
        elif line.startswith('### Time and positions') and day:
            if not any(mk in '\n'.join(lines[i+1:i+4]) for mk in MARKERS):
                done.add(day)
    return done


def generate(diary_text: str, frm: str, to: str, *, journey: Journey, phone_paths: Iterable[str],
             photos: str | None, places_path: str) -> tuple[Sections, list[str]]:
    """The sections, keyed by day, and the draft text for review."""
    lo = (D.datetime.fromisoformat(frm).replace(tzinfo=UTC) - D.timedelta(days=4)).timestamp()
    hi = (D.datetime.fromisoformat(to).replace(tzinfo=UTC) + D.timedelta(days=3)).timestamp()
    pics = photo_points(photos) if photos else []
    boat = journey.points(pics) + [p for p in pics if p.stop == 2]
    pics = [p for p in pics if journey.near(p.lat, p.lon)]
    phone = phone_points(phone_paths) + pics
    boat = sorted(p for p in boat if lo <= p.t <= hi)
    phone = clean_phone(sorted(p for p in phone if lo <= p.t <= hi), journey.near)
    pl, at_sea, ashore = read_places(places_path) if os.path.exists(places_path) else ([], [], [])
    boat, phone = not_ashore(boat, ashore), not_ashore(phone, ashore)
    done = hand_maintained(diary_text)
    fixes = journey.fixes()
    heads = [line for line in diary_text.split('\n') if line.startswith('## ')]
    zones = {}

    def window(day):
        if day not in zones:
            noon = D.datetime.fromisoformat(day).replace(hour=12, tzinfo=UTC).timestamp()
            zones[day] = day_window(day, day_zone(boat or phone, noon))
        return zones[day]

    pdays = sorted(window(m.group(1))[0] for m in
                   (re.match(r'## \w+ (\d{4}-\d\d-\d\d) - .* - ', h) for h in heads)
                   if m and lo <= window(m.group(1))[0] <= hi + 86400*30)
    sections, draft = {}, []
    for h in heads:
        m = re.match(r'## \w+ (\d{4}-\d\d-\d\d) - (.*)', h)
        if not m or ' - ' not in m.group(2) or not (frm <= m.group(1) <= to) or m.group(1) in done:
            continue
        d0, d1 = window(m.group(1))
        w0, w1 = d0 - 72*3600, d1 + 30*3600
        next_d0 = min([p for p in pdays if p > d0] + [9e12])
        ph = [p for p in phone if w0 <= p.t <= w1]
        bt = [p for p in boat if w0 <= p.t <= w1]
        # the phone is dense where it ran; it is useless where it was off or ashore
        ph_day = [p for p in ph if d0 <= p.t <= d1]
        legs = passages(bt, d0, d1, next_d0, at_sea, fixes=fixes)
        ph_legs = passages(ph, d0, d1, next_d0, at_sea, fixes=fixes) if len(ph_day) >= 100 else []
        if ph_legs and not any(_walking(g) for g in ph_legs) and (
                _worst(ph_legs) <= 2*3600 or (_worst(ph_legs) < _worst(legs) and len(ph_legs) >= len(legs))):
            # the phone's worth is its precision; wide windows mean it was off for a passage,
            # and then the boat's own track wins unless it is vaguer still
            legs = ph_legs
        else:
            # but a phone that ran for one move of the day still times that move
            legs = retime_ends(retime(legs, [g for g in ph_legs if not _walking(g)]), ph)
        if not legs:
            draft.append(f"\n{h}\n\n<!-- no passage found in the track data -->")
            continue
        srcs = set().union(*(g.srcs for g in legs))
        if 'nfl' in srcs and any(p.src == 'nfl' and p.lo == p.hi and p.t in journey.anchored
                                 for p in bt):
            srcs.add('photo')
        srcs = sorted(srcs)
        names = [n.strip() for n in m.group(2).split(' - ')]

        def name(pos, k, names=names, legs=legs):
            best = min(((hav(pos, (la, lo_)), n) for n, la, lo_ in pl), default=(9e9, ''))
            # a passage cut at the day window's edge can end on open water
            if any(hav(pos, a) < 400 for a in at_sea) and best[0] >= 400:
                return AT_SEA
            if best[0] < 1000:
                return best[1]
            if len(names) == len(legs) + 1 and '...' not in names[k]:
                return names[k]
            return 'XXX'
        lines = []
        for k, g in enumerate(legs):
            lines += render(g, name(g.a, k), name(g.b, k+1))
        sections[m.group(1)] = (srcs, lines)
        draft.append(f"\n{h}\n\n<!-- generated from {', '.join(srcs)} -->\n" + "\n".join(lines))
    return sections, draft


def _note(srcs: Iterable[str]) -> str:
    return (f"*(Derived afterwards from {' and '.join(SOURCE_NAMES[x] for x in srcs)} by "
            f"`{MARKER}` - not the tracker's own stop detection, which no longer ran.  "
            "Times are UTC; \"+/-\" and \"A .. B\" mark what the data cannot narrow down.)*")


def _generated(text: str, frm: str, to: str) -> list[str]:
    """Days in [frm, to] whose Time and positions section carries one of the markers."""
    out, day, lines = [], None, text.split('\n')
    for i, line in enumerate(lines):
        m = DAY_RE.match(line)
        if m:
            day = m.group(1)
        elif (line.startswith('### Time and positions') and day and frm <= day <= to
              and any(mk in '\n'.join(lines[i+1:i+4]) for mk in MARKERS)):
            out.append(day)
    return out


def dropped_days(text: str, sections: Sections, frm: str, to: str) -> list[str]:
    """Days whose generated section a rerun removes without writing a new one.

    That is right - the day no longer yields a passage, typically because its leg now
    belongs to the day before - but it also takes any hand edit made inside the section,
    so the caller should say so."""
    return [d for d in _generated(text, frm, to) if d not in sections]


def replace_sections(text: str, sections: Sections, frm: str, to: str) -> str:
    """Put each section before the day's first ### subsection, or at the end of the day.

    A section this tool wrote before, on a day in [frm, to], is dropped first, so a rerun
    replaces it; one outside the range is kept, as are hand-maintained ones."""
    done = hand_maintained(text)
    sections = {k: v for k, v in sections.items() if k not in done}
    lines = text.split('\n')
    kept, skipping, day = [], False, None
    for i, line in enumerate(lines):
        m = DAY_RE.match(line)
        if m:
            day = m.group(1)
        if (line.startswith('### Time and positions') and day and frm <= day <= to
                and any(mk in '\n'.join(lines[i+1:i+4]) for mk in MARKERS)):
            skipping = True
            while kept and kept[-1] == '':
                kept.pop()
            kept.append('')
            continue
        if skipping and (line.startswith('## ') or line.startswith('### ')):
            skipping = False
        if not skipping:
            kept.append(line)
    out, day, inserted = [], None, set()

    def flush():
        if day in sections and day not in inserted:
            while out and out[-1] == '':
                out.pop()
            srcs, body = sections[day]
            out.extend(['', '### Time and positions', '', _note(srcs), '', *body, ''])
            inserted.add(day)
    for line in kept:
        m = DAY_RE.match(line)
        if m or line.startswith('### '):
            flush()
        if m:
            day = m.group(1)
        out.append(line)
    flush()
    return '\n'.join(out)


def _default_phone_paths() -> list[str]:
    d = import_phone_export.phone_dir()
    return sorted(glob.glob(os.path.join(d, 'archive', '*.kml')) + glob.glob(os.path.join(d, '*.kml')))


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('diary', help='the diary-*.md file to read, and write with --write')
    ap.add_argument('frm', metavar='FROM', help='first day, YYYY-MM-DD')
    ap.add_argument('to', metavar='TO', help='last day, YYYY-MM-DD')
    ap.add_argument('--write', action='store_true', help='insert the sections into the diary')
    ap.add_argument('--phone', action='append',
                    help='a phone track .kml/.kmz (default: every one in <data>/../phone)')
    a = ap.parse_args(argv)
    with open(a.diary) as f:
        text = f.read()
    journey = Journey(os.path.join(config.JOURNEY, 'journey-snapshot.json'))
    sections, draft = generate(text, a.frm, a.to, journey=journey,
                               phone_paths=a.phone or _default_phone_paths(),
                               photos=config.PHOTOS,
                               places_path=os.path.join(config.JOURNEY, 'PLACES.md'))
    print('\n'.join(draft))
    print("\n## Passages in the track data on days without a passage heading\n")
    print('\n'.join(journey.unheaded(text, a.frm, a.to)))
    if a.write:
        for day in dropped_days(text, sections, a.frm, a.to):
            print(f"note: {day} lost its generated section and got no new one", file=sys.stderr)
        with open(a.diary, 'w') as f:
            f.write(replace_sections(text, sections, a.frm, a.to))
        print(f"inserted {len(sections)} sections into {a.diary}", file=sys.stderr)


if __name__ == '__main__':
    main()
