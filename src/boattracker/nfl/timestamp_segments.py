#!/usr/bin/env python3
"""Date Raymarine plotter segments from timestamped phone fixes.

The chartplotter records the best positions in this project and **no time at all**;
the phone records the time and a worse position. Joining the two back together is the
recurring operation here, and it has been done three times by session scripts
(`align_segs.py`, `make_timestamped.py`, `export_july2026.py`'s `jul26_match.py`) whose
hardcoded scratchpad paths no longer exist. This is that method, kept.

## Why a match rate is not the test

The boat revisits the same water — eight days of Galata Bay shuttling inside two square
kilometres, four calls at Chaika in a fortnight. Nearest-fix matching scores 100 % against
every one of those days at once. What separates the true day from a revisit is **order**:
walk the segment start to end, take the nearest phone fix to each point, and on the true
day the matched times come back increasing. Kendall's tau on (position along segment,
matched time) is therefore the discriminator, and `match()` refuses a segment whose tau
falls below `min_tau`.

The second test is speed: a matched window implying 44 kn is a wrong window, not a fast
boat. Callers should check `Match.knots` against roughly 0.4–9.0.

## Off-planet segments

From the diary, 2026-08-07: *"the navigator several times dropped GPS, and then later
decided we were in Peru, cruising in a circle in 109 knots"*. In `Tracks.gpx` that is 484
points across 11 entire segments of Tracks 64Xxx and 65, all at −12.04, −77.05, never
mixed into a good segment. `drop_off_planet()` removes them by distance from the corpus
median, so it catches the next such episode wherever the plotter decides it is.

Usage:
    python3 timestamp_segments.py Tracks.gpx --phone "~/Downloads/newmi/My Places (2).kmz" \\
            --tracks "Track 63,Track 64Xxx,Track 65,Track 66,Track 67W"
"""
from __future__ import annotations

import argparse
import math
import os
import re
from bisect import bisect_left
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from boattracker import geo
from boattracker.nfl import omaps_export

TRK = re.compile(r"<trk>.*?</trk>", re.S)
NAME = re.compile(r"<name>(.*?)</name>", re.S)
GUID = re.compile(r"<raymarine:GUID>(.*?)</raymarine:GUID>", re.S)
SEG = re.compile(r"<trkseg>(.*?)</trkseg>", re.S)
PT = re.compile(r"<trkpt\b([^>]*)>")
LAT = re.compile(r'lat="([-\d.]+)"')
LON = re.compile(r'lon="([-\d.]+)"')


## The shared haversine, under the name this module's callers already use.  It carried its
## own copy working in nautical miles directly, off a 3440.065 nm Earth radius; geo works in
## metres off 6371000 and divides, which is the same number to seven figures.
haversine_nm = geo.hav_nm


@dataclass
class Segment:
    track: str
    idx: int
    points: list[tuple[float, float]]
    guid: str = ""

    @property
    def nm(self) -> float:
        return sum(haversine_nm(a, b) for a, b in zip(self.points, self.points[1:]))

    @property
    def cumulative(self) -> list[float]:
        out, run = [0.0], 0.0
        for a, b in zip(self.points, self.points[1:]):
            run += haversine_nm(a, b)
            out.append(run)
        return out

    @property
    def centroid(self) -> tuple[float, float]:
        return (sum(p[0] for p in self.points) / len(self.points),
                sum(p[1] for p in self.points) / len(self.points))

    def __repr__(self):
        return f"<{self.track} s{self.idx} n={len(self.points)} {self.nm:.2f}nm>"


@dataclass
class Anchor:
    i: int            # index into segment.points
    t: datetime       # the matched phone fix's time
    metres: float     # how far the phone fix was


@dataclass
class Match:
    segment: Segment
    anchors: list[Anchor] = field(default_factory=list)
    tau: float = 0.0

    @property
    def t0(self) -> datetime:
        return self.anchors[0].t

    @property
    def t1(self) -> datetime:
        return self.anchors[-1].t

    @property
    def hours(self) -> float:
        return (self.t1 - self.t0).total_seconds() / 3600

    @property
    def knots(self) -> float:
        c = self.segment.cumulative
        span = c[self.anchors[-1].i] - c[self.anchors[0].i]
        return span / self.hours if self.hours > 0 else float("inf")


def load_segments(path: str, tracks: list[str] | None = None) -> list[Segment]:
    """Every `<trkseg>` in a Raymarine GPX, in file order.

    Raymarine writes `lon=` **before** `lat=`, so the attributes are read by name.
    """
    with open(os.path.expanduser(path), errors="replace") as f:
        txt = f.read()
    out = []
    for trk in TRK.findall(txt):
        m = NAME.search(trk)
        name = m.group(1).strip() if m else "?"
        if tracks and name not in tracks:
            continue
        g = GUID.search(trk)
        for i, seg in enumerate(SEG.findall(trk)):
            pts = []
            for pm in PT.finditer(seg):
                at = pm.group(1)
                la, lo = LAT.search(at), LON.search(at)
                if la and lo:
                    pts.append((float(la.group(1)), float(lo.group(1))))
            out.append(Segment(name, i, pts, g.group(1).strip() if g else ""))
    return out


def drop_off_planet(segments: list[Segment],
                    max_nm: float = 500.0) -> tuple[list[Segment], list[Segment]]:
    """Split off segments whose centroid is absurdly far from all the others.

    Measured against the median of every *point*, not the mean and not a median over
    segment centroids. Both of those can be captured: the plotter cut its Peru episode
    into eleven short segments, which outnumber the real ones in Track 65 while carrying
    3 % of the points.
    """
    real = [s for s in segments if s.points]
    if len(real) < 3:
        return list(segments), []
    pts = [p for s in real for p in s.points]
    mid = (sorted(p[0] for p in pts)[len(pts) // 2],
           sorted(p[1] for p in pts)[len(pts) // 2])
    kept, dropped = [], []
    for s in segments:
        if s.points and haversine_nm(s.centroid, mid) > max_nm:
            dropped.append(s)
        else:
            kept.append(s)
    return kept, dropped


def _kendall_tau(xs: list[float]) -> float:
    """Tau on a sequence already ordered by the other variable: +1 if increasing."""
    n = len(xs)
    if n < 2:
        return 0.0
    con = dis = 0
    for i in range(n):
        for j in range(i + 1, n):
            if xs[j] > xs[i]:
                con += 1
            elif xs[j] < xs[i]:
                dis += 1
    return (con - dis) / (con + dis) if con + dis else 0.0


def match(segment: Segment, fixes: list[omaps_export.Fix], radius_m: float = 150.0,
          samples: int = 200, min_anchors: int = 3, min_tau: float = 0.8,
          lo: datetime | None = None, hi: datetime | None = None) -> Match | None:
    """Date a segment against phone fixes, or return None if it cannot be dated.

    `lo`/`hi` restrict which fixes may be matched, which is how a caller pins a
    segment to a day the diary already names.
    """
    if len(segment.points) < 2 or not fixes:
        return None
    pool = [f for f in fixes if (lo is None or f.t >= lo) and (hi is None or f.t <= hi)]
    if not pool:
        return None

    # Spatial index on latitude: the pool is time-sorted, so a scan is O(n) per
    # sample and the whole 269k-fix export would be 54 million comparisons.
    by_lat = sorted(range(len(pool)), key=lambda i: pool[i].lat)
    lats = [pool[i].lat for i in by_lat]
    dlat = radius_m / 110540.0

    step = max(1, len(segment.points) // samples)
    anchors: list[Anchor] = []
    for i in range(0, len(segment.points), step):
        lat, lon = segment.points[i]
        best = None
        j = bisect_left(lats, lat - dlat)
        while j < len(lats) and lats[j] <= lat + dlat:
            f = pool[by_lat[j]]
            dx = (f.lon - lon) * 111320 * math.cos(math.radians(lat))
            dy = (f.lat - lat) * 110540
            d = math.hypot(dx, dy)
            if d <= radius_m and (best is None or d < best[0]):
                best = (d, f)
            j += 1
        if best:
            anchors.append(Anchor(i, best[1].t, best[0]))

    if len(anchors) < min_anchors:
        return None
    tau = _kendall_tau([a.t.timestamp() for a in anchors])
    if tau < min_tau:
        return None

    # Keep only the increasing subsequence, so one stray match cannot invert a
    # window that is otherwise sound.
    clean = [anchors[0]]
    for a in anchors[1:]:
        if a.t > clean[-1].t:
            clean.append(a)
    if len(clean) < 2 or clean[-1].t <= clean[0].t:
        return None
    return Match(segment, clean, tau)


def interpolate(segment: Segment, m: Match) -> list[datetime]:
    """A time for every point, spaced by along-track distance between anchors.

    Cumulative distance, never point index: the plotter samples by distance *and*
    by turn rate, so index spacing is not proportional to elapsed time. Points
    outside the matched range are extrapolated at the nearest anchor pair's own
    speed rather than left undated.
    """
    c = segment.cumulative
    pts = [(c[a.i], a.t.timestamp()) for a in m.anchors]
    out = []
    for x in c:
        k = bisect_left([p[0] for p in pts], x)
        if k <= 0:
            k = 1
        if k >= len(pts):
            k = len(pts) - 1
        (x0, t0), (x1, t1) = pts[k - 1], pts[k]
        f = 0.0 if x1 == x0 else (x - x0) / (x1 - x0)
        out.append(datetime.fromtimestamp(t0 + f * (t1 - t0), UTC))
    # Monotone by construction inside the range; clamp any extrapolated tail so a
    # zero-length hop cannot produce a backwards step.
    for i in range(1, len(out)):
        if out[i] < out[i - 1]:
            out[i] = out[i - 1] + timedelta(seconds=1)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("gpx")
    ap.add_argument("--phone", required=True, help="Organic Maps .kmz/.kml export")
    ap.add_argument("--tracks", help="comma-separated track names")
    ap.add_argument("--radius", type=float, default=150.0, help="metres")
    ap.add_argument("--min-nm", type=float, default=0.0)
    a = ap.parse_args()

    segs = load_segments(a.gpx, a.tracks.split(",") if a.tracks else None)
    segs, dropped = drop_off_planet(segs)
    for s in dropped:
        print(f"  DROPPED off-planet {s.track} s{s.idx}: {len(s.points)} points "
              f"at {s.centroid[0]:.4f},{s.centroid[1]:.4f}")
    fixes = omaps_export.load(a.phone)
    print(f"{len(segs)} segments, {len(fixes)} phone fixes\n")

    for s in segs:
        if len(s.points) < 2 or s.nm < a.min_nm:
            continue
        m = match(s, fixes, radius_m=a.radius)
        if not m:
            print(f"  {s.track} s{s.idx:<3d} {len(s.points):5d}pts {s.nm:7.2f}nm  "
                  f"UNDATED  {s.points[0][0]:.4f},{s.points[0][1]:.4f}")
            continue
        print(f"  {s.track} s{s.idx:<3d} {len(s.points):5d}pts {s.nm:7.2f}nm  "
              f"{m.t0:%Y-%m-%d %H:%M} .. {m.t1:%H:%M}Z  {m.hours:5.2f}h "
              f"{m.knots:5.2f}kn  tau={m.tau:.2f}  anchors={len(m.anchors)}")


if __name__ == "__main__":
    main()
