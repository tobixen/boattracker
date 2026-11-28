"""Counting time along a Raymarine plotter segment.

The plotter keeps no time, but from Track 8 on it lays a point every **step** while the boat
moves: 2.0 s for Tracks 8-19, 5.0 s from Track 20 (RAYMARINE-GPX.md, "Sampling interval",
measured against the phone). Before Track 8 it logged "by distance and time", which is no
clock, so nothing here applies there.

At anchor the step does not hold: the plotter lays points irregularly, but never faster than
the step. So time is counted as an interval per gap between two points:

* a gap of `STILL_M` or more, outside a stop, is one step, give or take `SLACK`;
* a shorter gap is at least `STOP_MIN` of a step: the plotter waits for some movement, at
  anchor and when berthing alike. Inside a stop it may have taken hours; alone, up to
  `SLOW_GAP_S`: at rest the plotter logs fewer points, not more, so a short stop at a fuel
  dock can leave only a gap or two, but a long one leaves a stop.

A stop is a minute's worth of steps over which the boat got nowhere: under `STILL_NET_M`
net, or wandering `WIGGLE` times further than it got. Points at anchor are irregular and a
swinging boat can move `STILL_M` in one step, so a run of short gaps alone would miss it.
Stops split the segment into moving stretches.

Anchors (phone fixes or photographs on the track, matched in order) are propagated both
ways along these intervals, which gives every point a window [lo, hi]: exact to a few
seconds across a moving stretch with an anchor in it, bounded on one side only across a
stop. A window with lo > hi means the anchors contradict the count; `consistent` says so.
"""

from __future__ import annotations

import bisect
import math
import re
from dataclasses import dataclass

from boattracker.geo import hav

SLACK = 0.01         # the measured step varies 4.99 .. 5.03 s, interquartile ±0.1-0.2 s
STOP_MIN = 0.9       # at anchor the plotter never logs faster than the step, give or take
STILL_M = 2.0        # a gap under this is no movement at either step
STOP_SECONDS = 60    # this long getting nowhere is a stop, not a slow moment
STILL_NET_M = 15.0   # ... nowhere: under half a knot net over that minute
WIGGLE = 3.0         # ... or this many times further along the points than net (a swing)
SLOW_GAP_S = 600     # the longest a short gap outside a stop may have taken
ANCHOR_M = 15        # a timed fix this close to a plotter point times it
ANCHOR_S = 10        # ... to within this: 15 m at a few knots, plus the fix's own jitter
TRACK_POINTS = 10_000  # the plotter starts a new track when one reaches this many points
ROLLOVER_SLACK = 20  # ... a few short of it here, the gaps between segments cost some
ROLLOVER_M = 100     # ... and the next track starts this close to where it stopped


def step(track: str) -> float | None:
    """Seconds per point under way for a plotter track, or None where it is no clock."""
    m = re.match(r'Track\s+(\d+)', track)
    if not m:
        return None  # the named season tracks predate Track 8
    n = int(m.group(1))
    return 2.0 if 8 <= n <= 19 else 5.0 if n >= 20 else None


def _still_runs(pts, step_s: float) -> list[bool]:
    """Per gap: whether it lies in a stop."""
    gaps = [hav(pts[i], pts[i+1]) for i in range(len(pts) - 1)]
    need = max(2, round(STOP_SECONDS / step_s))
    out = [False] * len(gaps)
    # a run of short gaps that long is a stop, however it drifted
    i = 0
    while i < len(gaps):
        j = i
        while j < len(gaps) and gaps[j] < STILL_M:
            j += 1
        if j - i >= need:
            out[i:j] = [True] * (j - i)
        i = max(j, i + 1)
    # and so is any window of that many gaps that got nowhere
    cum = [0.0]
    for g in gaps:
        cum.append(cum[-1] + g)
    for a in range(len(gaps) - need + 1):
        b = a + need
        net = hav(pts[a], pts[b])
        if net < STILL_NET_M or cum[b] - cum[a] > WIGGLE * net:
            # but a moving gap at either end of it is the boat arriving or leaving
            while a < b and gaps[a] >= STILL_M:
                a += 1
            while b > a and gaps[b-1] >= STILL_M:
                b -= 1
            out[a:b] = [True] * (b - a)
    return out


def stretches(pts, step_s: float) -> list[tuple[int, int]]:
    """Moving stretches as (first point, last point), split at stops."""
    still = _still_runs(pts, step_s)
    out, start = [], None
    for i, s in enumerate(still):
        if not s and start is None:
            start = i
        if s and start is not None:
            out.append((start, i))
            start = None
    if start is not None:
        out.append((start, len(pts) - 1))
    return out


def _gap_bounds(pts, step_s: float) -> list[tuple[float, float]]:
    # a short gap is the plotter waiting for movement, berthing as much as at anchor; alone,
    # it may be a short stop, but a long one would have left more points and made a stop
    runs = _still_runs(pts, step_s)
    return [(step_s * STOP_MIN, math.inf) if runs[i]
            else (step_s * STOP_MIN, max(SLOW_GAP_S, step_s)) if hav(pts[i], pts[i+1]) < STILL_M
            else (step_s * (1 - SLACK), step_s * (1 + SLACK))
            for i in range(len(pts) - 1)]


def windows(pts, anchors: dict[int, float], step_s: float) -> tuple[list[float], list[float]]:
    """(lo, hi) epoch seconds per point, from the anchors propagated along the count."""
    n = len(pts)
    g = _gap_bounds(pts, step_s)
    lo, hi = [-math.inf] * n, [math.inf] * n
    for i, t in anchors.items():
        lo[i], hi[i] = t - ANCHOR_S, t + ANCHOR_S
    for i in range(1, n):
        lo[i] = max(lo[i], lo[i-1] + g[i-1][0])
        hi[i] = min(hi[i], hi[i-1] + g[i-1][1])
    for i in range(n - 2, -1, -1):
        lo[i] = max(lo[i], lo[i+1] - g[i][1])
        hi[i] = min(hi[i], hi[i+1] - g[i][0])
    return lo, hi


def consistent(lo: list[float], hi: list[float]) -> bool:
    return all(a <= b for a, b in zip(lo, hi))


def duration(pts, i: int, j: int, step_s: float) -> tuple[float, float]:
    """(shortest, longest) seconds from point i to point j by the count."""
    g = _gap_bounds(pts, step_s)[i:j]
    return sum(a for a, _ in g), sum(b for _, b in g)


def anchors(pts, fixes, radius: float = ANCHOR_M, step_s: float | None = None) -> dict[int, float]:
    """{point index: epoch seconds} for timed fixes (lat, lon, t) on the track, in order.

    A fix matches its nearest point within `radius`. The boat revisits its own water, so only
    the longest run of matches increasing in both index and time is kept. With `step_s`, only
    fixes on a moving stretch count - a stop's points sit where the boat lay on other days
    too - and within each stretch only the largest group that agrees with the count, and
    only when that is two or more."""
    if step_s is not None:
        moving = set()
        for a, b in stretches(pts, step_s):
            moving.update(range(a, b + 1))
        found = _ordered(pts, fixes, radius)
        found = {i: t for i, t in found.items() if i in moving}
        out: dict[int, float] = {}
        for a, b in stretches(pts, step_s):
            group = _agreeing(pts, {i: t for i, t in found.items() if a <= i <= b}, step_s)
            # one match cannot tell the way back over the same water from the way out
            if len(group) >= 2:
                out.update(group)
        return dict(sorted(out.items()))
    return _ordered(pts, fixes, radius)


def _agreeing(pts, found: dict[int, float], step_s: float) -> dict[int, float]:
    """The largest group of one stretch's anchors that the count can join up."""
    g = _gap_bounds(pts, step_s)
    # running sums; an open-ended gap is counted apart, since inf - inf is no number
    cum_lo, cum_hi, open_ = [0.0], [0.0], [0]
    for a, b in g:
        cum_lo.append(cum_lo[-1] + a)
        cum_hi.append(cum_hi[-1] + (b if math.isfinite(b) else 0.0))
        open_.append(open_[-1] + (not math.isfinite(b)))
    best: dict[int, float] = {}
    for r, tr in found.items():
        group = {}
        for i, t in found.items():
            # the time from r to i by the count, slow gaps and all, either way round
            j, k = min(i, r), max(i, r)
            dmin = cum_lo[k] - cum_lo[j]
            dmax = math.inf if open_[k] > open_[j] else cum_hi[k] - cum_hi[j]
            dt = (t - tr) if i >= r else (tr - t)
            if dmin - 2 * ANCHOR_S <= dt <= dmax + 2 * ANCHOR_S:
                group[i] = t
        if len(group) > len(best):
            best = group
    return best


def _ordered(pts, fixes, radius: float) -> dict[int, float]:
    if not pts:
        return {}
    order = sorted(range(len(pts)), key=lambda k: pts[k][0])
    lats = [pts[k][0] for k in order]
    dlat = radius / 110_540
    hits = []
    for la, lo_, t in fixes:
        best = None
        a = bisect.bisect_left(lats, la - dlat)
        while a < len(lats) and lats[a] <= la + dlat:
            k = order[a]
            d = hav((la, lo_), pts[k])
            if d <= radius and (best is None or d < best[0]):
                best = (d, k)
            a += 1
        if best:
            hits.append((best[1], t))
    # longest run strictly increasing in time and in index: within one index the later
    # times go first, so no two of them can both be in it
    hits.sort(key=lambda h: (h[0], -h[1]))
    tails: list[float] = []
    idx: list[int] = []
    prev = [-1] * len(hits)
    for h, (_, t) in enumerate(hits):
        k = bisect.bisect_left(tails, t)
        if k == len(tails):
            tails.append(t)
            idx.append(h)
        else:
            tails[k] = t
            idx[k] = h
        prev[h] = idx[k-1] if k > 0 else -1
    out, h = {}, idx[-1] if idx else -1
    while h >= 0:
        out[hits[h][0]] = hits[h][1]
        h = prev[h]
    return dict(sorted(out.items()))


def rollovers(segments) -> list[tuple[float, float]]:
    """Where a full track ran out of points and the next went on: (lat, lon) of each seam.

    `segments` is (track, index, points) in plotter order. A track of TRACK_POINTS ends
    wherever the boat is, under way as often as not, so the seam is no stop; a short track
    ending where the next begins is the plotter switched off and on, which may well be.
    Only a seam the plotter was moving through counts: a full track can end at anchor too.
    """
    tracks: list[tuple[str, list]] = []
    for track, _idx, pts in segments:
        if not pts:
            continue
        if tracks and tracks[-1][0] == track:
            tracks[-1][1].append(pts)
        else:
            tracks.append((track, [pts]))
    out = []
    for (t0, segs), (t1, nxt) in zip(tracks, tracks[1:]):
        if step(t0) is None or step(t1) is None:
            continue  # the named tracks before Track 8 are no clock, and none is full
        if (sum(len(p) for p in segs) >= TRACK_POINTS - ROLLOVER_SLACK
                and hav(segs[-1][-1], nxt[0][0]) <= ROLLOVER_M
                and _moving_at(segs[-1], -1, step(t0))
                and _moving_at(nxt[0], 0, step(t1))):
            out.append(tuple(segs[-1][-1]))
    return out


def _moving_at(pts, end: int, step_s: float) -> bool:
    """Whether the plotter was under way at the first (0) or last (-1) point of pts: a
    minute's worth of points getting somewhere. Fewer points than that cannot tell, and
    count as under way; the full track and the shared position already say a seam."""
    k = max(2, round(STOP_SECONDS / step_s))
    tail = pts[-k-1:] if end == -1 else pts[:k+1]
    if len(tail) < 2:
        return True
    return hav(tail[0], tail[-1]) >= STILL_NET_M * (len(tail) - 1) / k


@dataclass
class Timed:
    """One plotter segment with its counted windows."""
    track: str
    seg: int
    points: list
    lo: list[float]
    hi: list[float]
    still: list[bool]        # per point: inside a stop
    step: float

    def duration(self, i: int, j: int) -> tuple[float, float]:
        return duration(self.points, i, j, self.step)


def timed(track: str, seg: int, pts, found: dict[int, float], step_s: float) -> Timed | None:
    """The windows for a segment, or None where its anchors contradict the count."""
    lo, hi = windows(pts, found, step_s)
    if not consistent(lo, hi):
        return None
    runs = _still_runs(pts, step_s)
    still = [False] * len(pts)
    for i, r in enumerate(runs):
        if r:
            still[i] = still[i+1] = True
    return Timed(track, seg, list(pts), lo, hi, still, step_s)
