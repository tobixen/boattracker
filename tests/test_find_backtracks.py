"""Tests for the backtrack finder.

The two that matter guard the ways this tool would be quietly useless rather than noisy:
a hairpin detector that counts tacking is a detector nobody will read, and a polyline
builder that keeps the renderer's duplicate vertices produces zero-length segments whose
bearing is arbitrary — which manufactures 180-degree turns out of nothing.
"""

import datetime

from boattracker.nfl import find_backtracks as fb

UTC = datetime.UTC


def rec(points, when, fix_id=1):
    """One journey fix whose rendered line is `points`, as [(lat, lon), ...]."""
    ms = when.timestamp() * 1000
    return {fix_id: {'point': (points[-1][0], points[-1][1], ms),
                     'source': 'test',
                     'line': [(la, lo, 0.0) for la, lo in points]}}


def test_duplicate_vertices_are_dropped():
    ## The renderer repeats a line's first point and its arrival. Left in, they are
    ## zero-length segments, and a zero-length segment's bearing is meaningless - which
    ## invents hairpins where the track is straight.
    when = datetime.datetime(2024, 5, 1, tzinfo=UTC)
    pts = [(59.0, 10.0), (59.0, 10.0), (59.1, 10.0), (59.2, 10.0), (59.2, 10.0)]
    out = fb.polyline(rec(pts, when))
    assert len(out) == 3
    assert not fb.hairpins(out)


def test_a_reversal_is_found():
    when = datetime.datetime(2024, 5, 1, tzinfo=UTC)
    ## north 11 km, then straight back south
    pts = [(59.0, 10.0), (59.1, 10.0), (59.0, 10.0)]
    found = fb.hairpins(fb.polyline(rec(pts, when)))
    assert len(found) == 1
    assert found[0]['turn'] > 170


def test_tacking_is_not_reported():
    ## Beating upwind reverses course every leg. Those legs are short, and `min_leg_m` is
    ## what keeps the report readable; without it every windward passage floods it.
    when = datetime.datetime(2024, 5, 1, tzinfo=UTC)
    pts = [(59.000, 10.000), (59.002, 10.002), (59.004, 10.000),
           (59.006, 10.002), (59.008, 10.000)]
    assert fb.hairpins(fb.polyline(rec(pts, when))) == []


def test_a_gentle_turn_is_not_a_hairpin():
    when = datetime.datetime(2024, 5, 1, tzinfo=UTC)
    pts = [(59.0, 10.0), (59.1, 10.0), (59.2, 10.1)]
    assert fb.hairpins(fb.polyline(rec(pts, when))) == []


def test_a_retrace_is_found_and_carries_its_elapsed_time():
    ## Out 11 km and back is 22 km of path returning to the start - well over the 2 nm
    ## default. The elapsed time is what tells a real day sail from an inserted chord,
    ## so it has to survive into the result.
    start = datetime.datetime(2024, 5, 1, 8, tzinfo=UTC)
    pts = [(59.0, 10.0), (59.05, 10.0), (59.1, 10.0), (59.05, 10.0), (59.0, 10.0)]
    records = rec(pts, start + datetime.timedelta(hours=6))
    found = fb.retraces(fb.polyline(records))
    assert len(found) == 1
    assert found[0]['apart_m'] < 400
    assert found[0]['path_nm'] > 10


def test_a_straight_passage_has_no_retrace():
    when = datetime.datetime(2024, 5, 1, tzinfo=UTC)
    pts = [(59.0 + 0.05 * i, 10.0) for i in range(8)]
    assert fb.retraces(fb.polyline(rec(pts, when))) == []


def test_turn_is_symmetric_and_wraps():
    assert fb.turn(10, 190) == 180
    assert fb.turn(350, 10) == 20
    assert fb.turn(10, 350) == 20


## ---------------------------------------------------------------- fix-level backtracks
##
## The hairpin and retrace tests above work inside the drawn line. These work at the
## joins between fixes, which is where a wrong timestamp or a duplicated upload shows up.


def journey(*entries):
    """Build a records dict the way noforeignland renders one.

    `entries` are `(fix_id, when, [(lat, lon), ...])` in **time order**, each giving the
    fix's *stored* path. The leading vertex repeating the previous fix's position is added
    here rather than by the caller, because that connector edge is the thing under test —
    a test that forgot it would be testing a line the site never draws.
    """
    out, prev = {}, None
    for fix_id, when, points in entries:
        line = ([prev] if prev else []) + list(points)
        out[fix_id] = {'point': (points[-1][0], points[-1][1], when.timestamp() * 1000),
                       'source': 'test', 'line': [(la, lo, 0.0) for la, lo in line]}
        prev = points[-1]
    return out


def at(hour, day=1):
    return datetime.datetime(2024, 5, day, hour, tzinfo=UTC)


def test_a_connector_landing_on_earlier_track_is_reported():
    ## The defect: fix 2 starts back where fix 1 began, so the map draws a straight line
    ## from the end of leg 1 to a point the boat had already passed.
    records = journey(
        (1, at(8), [(59.00, 10.0), (59.05, 10.0), (59.10, 10.0)]),
        (2, at(9), [(59.00, 10.0), (59.00, 10.1)]),
    )
    found = fb.connectors(fb.polyline(records))
    back = [c for c in found if c['back_nm']]
    assert len(back) == 1
    assert back[0]['fix_id'] == 2
    assert back[0]['back_nm'] > 5          # the 11 km it undid


def test_a_short_hop_back_to_the_same_berth_is_not_a_backtrack():
    ## Leaving a berth and returning to it a few metres away also lands on earlier track,
    ## but the chord is too short to draw anything. Scored on undone path alone this is the
    ## loudest thing in the whole journey - a berth revisited after a season "undoes"
    ## every mile since. The chord length is what separates the two.
    records = journey(
        (1, at(8), [(59.00, 10.0), (59.05, 10.02), (59.10, 10.0), (59.05, 9.98),
                    (59.00, 10.0)]),
        (2, at(12), [(59.0001, 10.0), (58.95, 10.0)]),
    )
    found = fb.connectors(fb.polyline(records))
    assert len(found) == 1                      # the join is seen ...
    assert found[0]['chord_nm'] < 0.1           # ... but it draws nothing
    assert found[0]['back_nm'] == 0


def test_track_from_an_earlier_season_is_not_backtracked_onto():
    ## Same water, a year apart. Out-of-order fixes and duplicates both land on track laid
    ## minutes or hours earlier, so the lookback is bounded in time; without that bound
    ## every returning cruise reports.
    records = journey(
        (1, datetime.datetime(2023, 5, 1, 8, tzinfo=UTC), [(59.00, 10.0), (59.10, 10.0)]),
        (2, datetime.datetime(2024, 5, 1, 8, tzinfo=UTC), [(59.00, 10.0), (59.00, 10.1)]),
    )
    assert [c for c in fb.connectors(fb.polyline(records)) if c['back_nm']] == []


def test_an_offshore_gap_is_not_a_backtrack():
    ## Out of GSM coverage the tracker stops, and the join is a long straight chord. It is
    ## forward-going and must not be reported, or every ocean passage floods the output.
    records = journey(
        (1, at(8), [(59.0, 10.0), (59.1, 10.0)]),
        (2, at(20), [(60.0, 10.0), (60.1, 10.0)]),
    )
    found = fb.connectors(fb.polyline(records))
    assert [c for c in found if c['back_nm']] == []


def test_an_impossible_speed_is_flagged_even_going_forward():
    ## 60 nm in six minutes is not a gap in the record, it is a wrong timestamp.
    records = journey(
        (1, at(8), [(59.0, 10.0), (59.1, 10.0)]),
        (2, datetime.datetime(2024, 5, 1, 8, 6, tzinfo=UTC), [(60.1, 10.0), (60.2, 10.0)]),
    )
    fast = [c for c in fb.connectors(fb.polyline(records)) if c['knots'] > 15]
    assert len(fast) == 1


def test_two_fixes_in_the_wrong_time_order_are_found():
    ## Positions run south to north, but the middle two carry swapped timestamps, so the
    ## line goes up, back down, and up again.
    records = journey(
        (1, at(8), [(59.0, 10.0)]),
        (2, at(9), [(59.2, 10.0)]),
        (3, at(10), [(59.1, 10.0)]),
        (4, at(11), [(59.3, 10.0)]),
    )
    found = fb.swaps(fb.fix_sequence(records))
    assert len(found) == 1
    assert (found[0]['first'], found[0]['second']) == (2, 3)
    assert found[0]['gain_nm'] > 5


def test_fixes_already_in_order_suggest_no_swap():
    records = journey(*[(i, at(8 + i), [(59.0 + 0.1 * i, 10.0)]) for i in range(1, 6)])
    assert fb.swaps(fb.fix_sequence(records)) == []


def test_an_out_and_back_day_is_not_read_as_a_swap():
    ## Sailing out to an island and home again reverses course for real. Swapping the
    ## turning point with its neighbour saves nothing, and that is what keeps it quiet.
    records = journey(
        (1, at(8), [(59.0, 10.0)]),
        (2, at(10), [(59.2, 10.0)]),
        (3, at(14), [(59.0, 10.0)]),
        (4, at(16), [(58.8, 10.0)]),
    )
    assert fb.swaps(fb.fix_sequence(records)) == []


def test_two_fixes_at_one_place_and_time_are_paired():
    records = journey(
        (1, at(8), [(59.0, 10.0)]),
        (2, datetime.datetime(2024, 5, 1, 8, 10, tzinfo=UTC), [(59.0001, 10.0001)]),
    )
    found = fb.duplicate_fixes(fb.fix_sequence(records))
    assert len(found) == 1
    assert found[0]['apart_m'] < 50


def test_returning_to_a_berth_a_year_later_is_not_a_duplicate():
    records = journey(
        (1, datetime.datetime(2023, 5, 1, 8, tzinfo=UTC), [(59.0, 10.0)]),
        (2, datetime.datetime(2024, 5, 1, 8, tzinfo=UTC), [(59.0, 10.0)]),
    )
    assert fb.duplicate_fixes(fb.fix_sequence(records)) == []


## -------------------------------------------------------------- overlapping time windows
##
## `connectors` sees this class only when the chord happens to land on already-drawn track
## or implies an impossible speed. Two real cases (2024-03-03 and 2024-03-14) do neither and
## were found by hand. The vertex timestamps say it outright, so ask them directly.


def timed_journey(*entries):
    """`journey()`, but each vertex carries its own instant.

    `entries` are `(fix_id, when, [(lat, lon, vertex_when), ...])`. The leading connector
    is added here for the same reason as in `journey()` — it is part of what is drawn, and
    a report that forgot to skip it would fire on every join in the journey.
    """
    out, prev = {}, None
    for fix_id, when, points in entries:
        line = ([prev] if prev else []) + [(la, lo, t.timestamp() * 1000)
                                           for la, lo, t in points]
        out[fix_id] = {'point': (points[-1][0], points[-1][1], when.timestamp() * 1000),
                       'source': 'test', 'line': line}
        prev = (points[-1][0], points[-1][1], points[-1][2].timestamp() * 1000)
    return out


def test_a_line_covering_a_window_the_previous_fix_has_passed_is_reported():
    ## The shape behind the 180 nm Marmara defect: fix 1 is a short fragment stamped after
    ## the full passage fix 2 records, so the map draws the fragment, jumps back to where
    ## the passage began, and sails it again.
    records = timed_journey(
        (1, at(12), [(59.30, 10.0, at(12))]),
        (2, at(13), [(59.00, 10.0, at(9)), (59.20, 10.0, at(11)), (59.35, 10.0, at(13))]),
    )
    found = fb.windows(fb.fix_sequence(records))
    assert len(found) == 1
    assert found[0]['fix_id'] == 2 and found[0]['from_fix'] == 1
    assert abs(found[0]['overlap_hours'] - 3) < 0.01
    assert found[0]['jump_nm'] > 15          # 59.30 back to 59.00


def test_a_forward_going_sequence_reports_no_window():
    records = timed_journey(
        (1, at(9), [(59.0, 10.0, at(8)), (59.1, 10.0, at(9))]),
        (2, at(12), [(59.2, 10.0, at(10)), (59.4, 10.0, at(12))]),
    )
    assert fb.windows(fb.fix_sequence(records)) == []


def test_the_leading_connector_does_not_count_as_an_early_vertex():
    ## The connector repeats the previous fix's own arrival, so its timestamp is at or
    ## before that fix's. Counted, it would report every join in the journey.
    records = timed_journey(
        (1, at(9), [(59.0, 10.0, at(8)), (59.1, 10.0, at(9))]),
        (2, at(12), [(59.3, 10.0, at(11)), (59.5, 10.0, at(12))]),
    )
    assert fb.windows(fb.fix_sequence(records)) == []


def test_an_untimed_line_is_not_judged():
    ## Many 2023 vertices carry epoch 0 - no time at all. Nothing can be concluded about
    ## their window, and treating 1970 as "before" would report every one of them.
    records = journey(
        (1, at(12), [(59.3, 10.0)]),
        (2, at(13), [(59.0, 10.0), (59.35, 10.0)]),
    )
    assert fb.windows(fb.fix_sequence(records)) == []


def test_an_overlap_that_draws_nothing_is_not_reported():
    ## Two records of one berth overlap in time but sit on top of each other, so the
    ## renderer draws no visible jump. Same reasoning as `min_chord_m` in `connectors`.
    records = timed_journey(
        (1, at(12), [(59.0000, 10.0, at(12))]),
        (2, at(13), [(59.0001, 10.0, at(9)), (59.0002, 10.0, at(13))]),
    )
    assert fb.windows(fb.fix_sequence(records)) == []
