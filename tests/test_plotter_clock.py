"""Tests for counting time along a plotter segment.

Under way the plotter lays a point every step (5.0 s from Track 20, 2.0 s for Tracks 8-19),
so counting points is a clock; at anchor it lays them irregularly, never faster. The tests
pin both halves: exact times where a moving stretch carries an anchor, and only a bound
across a stop, which is all the stop's points can say.
"""

import math

from boattracker.nfl import plotter_clock as pc


def moving(n, start=(41.0, 28.9), metres=12.0):
    """n points due north, `metres` apart: a boat at ~5 kn with a 5 s step."""
    dlat = metres / 111_195
    return [(start[0] + k * dlat, start[1]) for k in range(n)]


def still(n, at):
    """n points jittering under a metre: a boat at anchor."""
    return [(at[0] + (k % 3) * 2e-6, at[1]) for k in range(n)]


def test_the_step_is_known_only_from_track_8():
    assert pc.step("Track 7") is None
    assert pc.step("ToSantorini2024") is None
    assert pc.step("Track 8") == 2.0
    assert pc.step("Track 19") == 2.0
    assert pc.step("Track 20") == 5.0
    assert pc.step("Track 67W") == 5.0
    assert pc.step("Track 57.202509") == 5.0


def test_an_anchor_in_a_moving_stretch_times_every_point_of_it():
    pts = moving(101)
    lo, hi = pc.windows(pts, {50: 1000.0}, 5.0)
    assert abs(lo[0] - (1000 - 250)) < 16 and abs(hi[0] - (1000 - 250)) < 16
    assert abs(lo[100] - 1250) < 16 and abs(hi[100] - 1250) < 16
    assert lo[50] == 1000.0 - pc.ANCHOR_S and hi[50] == 1000.0 + pc.ANCHOR_S


def test_a_stop_bounds_the_time_on_one_side_only():
    # 08-29 s3: under way, then 118 points at anchor, the phone at the very last one
    pts = moving(100) + still(118, moving(100)[-1])
    lo, hi = pc.windows(pts, {217: 10_000.0}, 5.0)
    assert math.isinf(lo[99])                      # how long it lay there is unknown
    assert hi[99] <= 10_000 + pc.ANCHOR_S - 118 * 5 * 0.9 + 1  # but it lay there at least that long
    # and the passage itself is still counted exactly
    assert abs(pc.duration(pts, 0, 99, 5.0)[0] - 99 * 5) < 12
    assert abs(pc.duration(pts, 0, 99, 5.0)[1] - 99 * 5) < 12


def test_two_anchors_squeeze_a_stop_from_both_sides():
    pts = moving(50) + still(40, moving(50)[-1]) + moving(50, start=moving(50)[-1])
    lo, hi = pc.windows(pts, {0: 0.0, 139: 3000.0}, 5.0)
    assert math.isfinite(lo[60]) and math.isfinite(hi[60])
    assert lo[60] <= hi[60]


def test_contradicting_anchors_are_reported_not_hidden():
    # two anchors 10 points apart, 1000 s apart: not a 5 s step under way
    pts = moving(20)
    lo, hi = pc.windows(pts, {0: 0.0, 10: 1000.0}, 5.0)
    assert any(a > b for a, b in zip(lo, hi))
    assert pc.consistent(lo, hi) is False


def test_moving_stretches_are_split_at_stops():
    pts = moving(50) + still(40, moving(50)[-1]) + moving(30, start=moving(50)[-1])
    assert pc.stretches(pts, 5.0) == [(0, 49), (90, 119)]


def test_anchors_are_taken_from_fixes_on_the_track_in_order():
    pts = moving(100)
    fixes = [(pts[10][0], pts[10][1], 100.0), (pts[40][0], pts[40][1], 250.0),
             (pts[60][0], pts[60][1], 350.0),
             (pts[30][0], pts[30][1], 900.0),    # out of order: a later revisit, dropped
             (41.5, 28.9, 200.0)]                # nowhere near the track
    assert pc.anchors(pts, fixes) == {10: 100.0, 40: 250.0, 60: 350.0}


def test_anchors_at_a_stop_or_against_the_count_are_dropped():
    # the phone at a twice-used anchorage matches the stop's points to the wrong night; and
    # one fix on the moving stretch disagrees with the rest by ten minutes
    pts = still(30, (41.0, 28.9)) + moving(100, start=(41.0, 28.9))
    fixes = [(41.0, 28.9, 1.0),                                 # at the stop: dropped
             (pts[40][0], pts[40][1], 10_000.0), (pts[60][0], pts[60][1], 10_100.0),
             (pts[80][0], pts[80][1], 10_200.0),
             (pts[100][0], pts[100][1], 10_900.0)]              # 10 minutes off: dropped
    a = pc.anchors(pts, fixes, step_s=5.0)
    assert sorted(a) == [40, 60, 80]
    lo, hi = pc.windows(pts, a, 5.0)
    assert pc.consistent(lo, hi)


def test_a_lone_anchor_does_not_time_a_stretch():
    # 2025-08-29 s3: the evening return retraces the morning's route the other way, and one
    # phone fix from the morning lies on it; a single match cannot tell direction or day
    pts = moving(100)
    assert pc.anchors(pts, [(pts[50][0], pts[50][1], 1000.0)], step_s=5.0) == {}


def test_slow_gaps_under_way_take_longer_than_the_step():
    # 2025-08-29 s2, berthing at Zeyport: 17 points in 108 s, the plotter waiting for movement.
    # Eight 1 m gaps are too few for a stop, but each took longer than the step.
    a = moving(10)
    b = moving(9, start=a[-1], metres=1.0)[1:]
    c = moving(10, start=b[-1])[1:]
    pts = a + b + c
    strict = (len(pts) - 1) * 5.0
    lo, hi = pc.windows(pts, {0: 0.0, len(pts) - 1: strict + 60}, 5.0)
    assert pc.consistent(lo, hi)


def test_an_isolated_slow_gap_may_take_minutes_but_not_hours():
    # 2025-08-29 s3: a couple of short gaps leaving the berth must not make the passage's
    # duration unbounded; but at rest the plotter logs fewer points, not more, so one gap
    # may be a short stop of several minutes (RAYMARINE-GPX.md)
    a = moving(50)
    pts = a + [(a[-1][0] + 1e-6, a[-1][1])] + moving(50, start=(a[-1][0] + 1e-6, a[-1][1]))[1:]
    lo_d, hi_d = pc.duration(pts, 0, len(pts) - 1, 5.0)
    assert math.isfinite(hi_d)
    assert hi_d >= (len(pts) - 2) * 5 * 0.99 + 300


def swinging(n, at):
    """n points at anchor, mostly under a metre apart but a 3 m swing every fifth gap."""
    out, lat = [], at[0]
    for k in range(n):
        lat += (3 if k % 5 == 4 else 0.5) / 111_195 * (1 if (k // 10) % 2 else -1)
        out.append((lat, at[1]))
    return out


def test_a_swinging_anchorage_is_a_stop():
    # RAYMARINE-GPX.md: a boat swinging on its anchor sometimes moves 2 m in one step
    pts = swinging(200, (41.0, 28.9))
    pts += moving(100, start=pts[-1])[1:]
    got = pc.stretches(pts, 5.0)
    assert not any(a <= 50 <= b for a, b in got)
    assert got and got[-1][1] == len(pts) - 1 and got[-1][0] >= 190


def test_anchors_either_side_of_a_slow_moment_agree():
    # a berthing slowdown: four short gaps that took minutes between two good fixes
    a = moving(40)
    b = [(a[-1][0] + k * 1e-6, a[-1][1]) for k in range(1, 5)]
    c = moving(40, start=b[-1])[1:]
    pts = a + b + c
    t_b = 39 * 5.0 + 4 * 120.0      # each short gap took two minutes
    fixes = [(pts[10][0], pts[10][1], 50.0), (pts[30][0], pts[30][1], 150.0),
             (pts[50][0], pts[50][1], t_b + 7 * 5.0), (pts[70][0], pts[70][1], t_b + 27 * 5.0)]
    assert sorted(pc.anchors(pts, fixes, step_s=5.0)) == [10, 30, 50, 70]


def test_two_fixes_on_one_point_count_once_when_ordering():
    # three fixes on point 10 would outvote two good fixes further on
    pts = moving(100)
    fixes = [(pts[10][0], pts[10][1], 100.0), (pts[10][0], pts[10][1], 101.0),
             (pts[10][0], pts[10][1], 102.0),
             (pts[30][0], pts[30][1], 50.0), (pts[40][0], pts[40][1], 60.0)]
    assert pc.anchors(pts, fixes) == {30: 50.0, 40: 60.0}


def test_a_track_that_ran_out_of_points_rolls_over_into_the_next():
    # the plotter starts a new track at 10 000 points, wherever the boat is
    a = moving(9990)
    b = moving(100, start=a[-1])
    c = moving(100, start=(41.5, 28.9))
    segs = [("Track 36", 0, a), ("Track 37", 0, b), ("Track 38", 0, c)]
    assert pc.rollovers(segs) == [a[-1]]
    # a short track ending where the next begins is the plotter switched off and on
    assert pc.rollovers([("Track 36", 0, a[:500]), ("Track 37", 0, b)]) == []


def test_a_track_that_ran_out_of_points_at_anchor_is_no_seam_under_way():
    # 2025-08-23, Kardirga Koyu: Track 46 filled up while the boat lay at anchor overnight
    a = moving(9890) + still(100, moving(9890)[-1])
    b = still(50, a[-1]) + moving(100, start=a[-1])
    assert pc.rollovers([("Track 46", 0, a), ("Track 47", 0, b)]) == []


def test_a_seam_with_a_short_first_segment_after_it_still_counts():
    # the next track's first segment can be 11 points long; too short to tell, not still
    a = moving(9990)
    b = moving(8, start=a[-1])
    assert pc.rollovers([("Track 36", 0, a), ("Track 37", 0, b), ("Track 37", 1, moving(50))]) == [a[-1]]


def test_slow_sailing_on_a_two_second_track_is_moving_at_a_seam():
    # Tracks 8-19 log every 2 s: under 2 kn every gap is under STILL_M, yet the boat moves
    a = moving(9990, metres=1.5)
    b = moving(100, start=a[-1], metres=1.5)
    assert pc.rollovers([("Track 12", 0, a), ("Track 13", 0, b)]) == [a[-1]]
