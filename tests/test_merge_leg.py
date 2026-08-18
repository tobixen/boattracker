"""Tests for merging one leg's sources into a single timed track.

The rule being implemented is the owner's: **one fix, one leg, a timestamp on every
vertex**, built from the plotter for position and the tracker for time. A leg runs from one
significant stop to the next, and the diary headings are where those stops are recorded.

The three days that prompted it are each a single leg held on the journey as 11, 5 and 10
fixes — a tracker leg, one or more plotter fills uploaded earlier, and some stationary
stubs. Merging them means taking every timed vertex in the window, ordering it, and
splicing plotter geometry into whatever gap is left.
"""

from boattracker.nfl import merge_leg as M

MS = 1000
H = 3600 * MS


def v(lat, lon, ms):
    return (lat, lon, ms)


def test_vertices_are_gathered_in_time_order_across_lines():
    ## The journey holds a leg as several fixes; their vertices interleave in time.
    lines = [[v(59.0, 10.0, 3 * H), v(59.1, 10.0, 4 * H)],
             [v(58.8, 10.0, 1 * H), v(58.9, 10.0, 2 * H)]]
    out = M.collect(lines, 0, 10 * H)
    assert [x[2] for x in out] == [1 * H, 2 * H, 3 * H, 4 * H]


def test_vertices_outside_the_window_are_dropped():
    lines = [[v(59.0, 10.0, 1 * H), v(59.1, 10.0, 5 * H)]]
    out = M.collect(lines, 2 * H, 4 * H)
    assert out == []


def test_untimed_vertices_are_dropped():
    ## Epoch 0 is "no time", and a merged leg is defined by its times.
    lines = [[v(59.0, 10.0, 0), v(59.1, 10.0, 2 * H)]]
    assert [x[2] for x in M.collect(lines, 0, 10 * H)] == [2 * H]


def test_one_moment_recorded_twice_is_kept_once():
    ## The tracker and a plotter fill both hold the arrival; the merge must not double it.
    lines = [[v(59.0, 10.0, 1 * H)], [v(59.0, 10.0, 1 * H)]]
    assert len(M.collect(lines, 0, 10 * H)) == 1


def test_near_identical_positions_at_the_same_instant_collapse():
    ## Two sources for one moment agree to a few metres rather than exactly.
    lines = [[v(59.00000, 10.0, 1 * H)], [v(59.00002, 10.0, 1 * H)]]
    assert len(M.collect(lines, 0, 10 * H)) == 1


def test_a_gap_over_the_threshold_is_found():
    pts = [v(59.0, 10.0, 1 * H), v(59.1, 10.0, 2 * H)]      # ~6 nm apart
    assert M.gaps(pts, 1.0) == [0]


def test_a_short_hop_is_not_a_gap():
    pts = [v(59.000, 10.0, 1 * H), v(59.005, 10.0, 2 * H)]  # ~0.3 nm
    assert M.gaps(pts, 1.0) == []


def test_a_spliced_slice_is_timed_across_the_window_it_fills():
    ## Times come from the tracker's clock at each end, spread by distance along the slice.
    sl = [(59.0, 10.0), (59.05, 10.0), (59.1, 10.0)]
    timed = M.time_across(sl, 1 * H, 3 * H)
    assert timed[0][2] == 1 * H and timed[-1][2] == 3 * H
    assert timed[1][2] == 2 * H            # the midpoint by distance is the midpoint in time


def test_timing_a_slice_is_monotonic():
    sl = [(59.0, 10.0), (59.02, 10.0), (59.05, 10.0), (59.1, 10.0)]
    ts = [t[2] for t in M.time_across(sl, 0, 4 * H)]
    assert ts == sorted(ts)


def test_a_merged_leg_keeps_its_times_strictly_increasing():
    ## Splicing must not produce a vertex that goes backwards in time - the renderer would
    ## draw the leg doubling back, which is the whole defect this exists to remove.
    pts = [v(59.0, 10.0, 1 * H), v(59.1, 10.0, 3 * H)]
    slices = {0: [(59.0, 10.0), (59.04, 10.0), (59.07, 10.0), (59.1, 10.0)]}
    merged = M.splice(pts, slices)
    ts = [p[2] for p in merged]
    assert ts == sorted(ts) and len(set(ts)) == len(ts)


def test_splicing_replaces_the_gap_and_keeps_the_rest():
    pts = [v(58.9, 10.0, 0), v(59.0, 10.0, 1 * H), v(59.1, 10.0, 3 * H)]
    slices = {1: [(59.0, 10.0), (59.05, 10.0), (59.1, 10.0)]}
    merged = M.splice(pts, slices)
    assert merged[0][:2] == (58.9, 10.0)          # untouched
    assert (59.05, 10.0) in [p[:2] for p in merged]  # the slice went in
    assert merged[-1][:2] == (59.1, 10.0)


def test_splicing_nothing_returns_the_input():
    pts = [v(59.0, 10.0, 1 * H), v(59.1, 10.0, 3 * H)]
    assert M.splice(pts, {}) == pts


## --------------------------------------------------------------- writing the merged leg
##
## `leg_export.build` is the usual GPX writer here, and it is the wrong one for this job: it
## re-times points across the leg by cumulative distance. That is right when the source has
## no times of its own, and destructive here, where every vertex already carries the
## tracker's real clock and the boat's speed varied along the way.


def test_the_written_gpx_keeps_each_vertex_time():
    pts = [v(59.0, 10.0, 1 * H), v(59.05, 10.0, 2 * H), v(59.1, 10.0, 6 * H)]
    xml = M.gpx(pts, 'test leg')
    assert '<time>1970-01-01T01:00:00Z</time>' in xml
    assert '<time>1970-01-01T02:00:00Z</time>' in xml
    assert '<time>1970-01-01T06:00:00Z</time>' in xml


def test_the_written_gpx_is_parseable():
    import xml.etree.ElementTree as ET
    pts = [v(59.0, 10.0, 1 * H), v(59.1, 10.0, 2 * H)]
    ET.fromstring(M.gpx(pts, 'test leg'))


def test_the_creator_does_not_claim_to_be_a_plain_raymarine_export():
    ## The importer derives the displayed source label from `creator`, so a merged leg must
    ## not be badged as a pure chartplotter export.
    pts = [v(59.0, 10.0, 1 * H), v(59.1, 10.0, 2 * H)]
    xml = M.gpx(pts, 'test leg')
    assert 'merged' in xml.lower()
    assert 'tracker' in xml.lower()


def test_the_eml_carries_the_gpx_as_an_attachment():
    pts = [v(59.0, 10.0, 1 * H), v(59.1, 10.0, 2 * H)]
    raw = M.eml(M.gpx(pts, 'test leg'), 'test leg', 'test.gpx').decode('utf-8', 'replace')
    assert 'application/gpx+xml' in raw
    assert 'filename="test.gpx"' in raw
    assert raw.startswith('From: ') or '\nFrom: ' in raw


def test_the_eml_addresses_come_from_leg_export():
    ## One copy of the importer's address and the authorised sender, not two.
    from boattracker.nfl import leg_export as LE
    pts = [v(59.0, 10.0, 1 * H), v(59.1, 10.0, 2 * H)]
    raw = M.eml(M.gpx(pts, 'x'), 'x', 'x.gpx').decode('utf-8', 'replace')
    assert LE.TO in raw and LE.FROM in raw


## ------------------------------------------------------- a slice has to be sailable
##
## `covering_slice` accepts any plotter slice whose two ends are within a mile of the gap's
## ends, on any segment. It does not check that the boat could have sailed it in the time
## available, and passing `--tracks` disables the date filter in `source_segments`, so a
## segment from a different month of the same track is eligible. On 2024-04-03 that offered
## 11.11 nm of track to bridge a 4.54 nm gap of 52 minutes — 12.8 kn, which the boat did not
## do. Two of the six fills that run proposed were like that.


def test_a_slice_matching_its_gap_is_plausible():
    assert M.plausible_slice(slice_nm=8.35, gap_nm=8.35, hours=1.5)


def test_a_slice_far_longer_than_its_gap_is_rejected():
    ## The 2024-04-03 case: 11.11 nm of track across a 4.54 nm gap in 52 minutes.
    assert not M.plausible_slice(slice_nm=11.11, gap_nm=4.54, hours=0.87)


def test_a_little_wandering_is_allowed():
    ## Tacking or rounding a headland makes the sailed track longer than the straight line.
    assert M.plausible_slice(slice_nm=5.4, gap_nm=4.5, hours=1.2)


def test_an_impossible_speed_is_rejected_even_when_the_shape_matches():
    ## Same length as the gap, but no time to sail it.
    assert not M.plausible_slice(slice_nm=8.0, gap_nm=8.0, hours=0.1)


def test_a_zero_length_window_is_not_plausible():
    assert not M.plausible_slice(slice_nm=4.0, gap_nm=4.0, hours=0.0)


## ------------------------------------------- re-timing plotter data from the tracker clock
##
## The plotter records no time at all; every timestamp on Raymarine data here was *assigned*
## by an export script or by hand. That is where the impossible speeds come from: on
## 2024-04-03 every implausible step in the merged leg has at least one Raymarine end and
## five of six have both, alternating between two fixes - `...971575 -> ...971576 ->
## ...971575` - which is two assigned timestamps overlapping, so the line ping-pongs between
## two parallel tracks. No step is tracker-to-tracker.
##
## The precedence rule says the tracker owns the clock, so the repair is to read each plotter
## point's time off the tracker line at the place the plotter says the boat was. Checked
## against a known case, that method put the 2023-06-05 fragment's end at 02:56 against its
## own stamp of 02:51 - five minutes.

BACKBONE = [(59.00, 10.0, 0), (59.05, 10.0, 1 * H), (59.10, 10.0, 2 * H)]


def test_a_point_on_the_backbone_takes_its_time():
    out = M.retime([(59.05, 10.0, 999)], BACKBONE)
    assert out[0][2] == 1 * H


def test_a_point_between_two_backbone_vertices_is_interpolated():
    out = M.retime([(59.025, 10.0, 999)], BACKBONE)
    assert abs(out[0][2] - 0.5 * H) < 60 * 1000


def test_retimed_points_come_back_in_time_order():
    pts = [(59.08, 10.0, 999), (59.02, 10.0, 999)]
    out = M.retime(pts, BACKBONE)
    assert [p[2] for p in out] == sorted(p[2] for p in out)


def test_a_point_far_from_the_backbone_is_dropped():
    ## Nothing on the tracker line speaks for water it never went near, and guessing a time
    ## there is what produced the problem in the first place.
    out = M.retime([(58.0, 12.0, 999)], BACKBONE, max_m=2000)
    assert out == []


def test_an_empty_backbone_retimes_nothing():
    assert M.retime([(59.05, 10.0, 999)], []) == []


## ------------------------------------------------ the merged leg has to be sailable too
##
## Merging does not resolve a contradiction between sources; it moves it inside one line.
## 2024-04-03 holds two pairs the backtrack sweep flagged as *not* GSM dropouts, and merging
## them produced consecutive vertices implying 67 and 76 kn. A jump between fixes at least
## announces itself in `find_backtracks.py`; the same error inside a single line is invisible
## there, so the merge has to check its own output.


def test_an_impossible_step_in_the_merged_leg_is_reported():
    pts = [v(59.0, 10.0, 0), v(59.1, 10.0, 60 * 1000)]   # ~6 nm in one minute
    bad = M.implausible_steps(pts, max_knots=12.0)
    assert len(bad) == 1 and bad[0][0] == 0


def test_ordinary_sailing_is_not_reported():
    pts = [v(59.0, 10.0, 0), v(59.1, 10.0, 3600 * 1000)]  # ~6 nm in an hour
    assert M.implausible_steps(pts, max_knots=12.0) == []


def test_a_zero_length_step_is_not_reported():
    ## Two records of one moment at one place; nothing is implied about speed.
    pts = [v(59.0, 10.0, 0), v(59.0, 10.0, 1000)]
    assert M.implausible_steps(pts, max_knots=12.0) == []


## ------------------------------------------------------------- re-timing a bad join
##
## 2024-04-02/03 is eight slices of one segment, Track 4 s88, in the correct point order.
## The only defect is that adjacent slices carry assigned times that overlap by a couple of
## minutes - 6755398652971576 starts 20:32:45 while 6755398652971575 runs to 20:34:57 - so
## the joins imply 12 to 20 kn across one s88 point spacing of ~850 m. Nothing is in the
## wrong place; the times are just too tight where two uploads meet.
##
## The repair has to be local: redistribute time across the smallest window that fixes the
## join, and leave every vertex whose timing is already consistent exactly where it is.


def test_a_too_fast_join_is_slowed_to_something_sailable():
    ## 6 nm in one minute between two otherwise sane hours.
    pts = [v(59.0, 10.0, 0), v(59.1, 10.0, 60 * 1000), v(59.2, 10.0, 4 * H)]
    out = M.smooth_joins(pts, max_knots=12.0)
    assert M.implausible_steps(out, max_knots=12.0) == []


def test_the_endpoints_of_the_leg_are_never_moved():
    pts = [v(59.0, 10.0, 0), v(59.1, 10.0, 60 * 1000), v(59.2, 10.0, 4 * H)]
    out = M.smooth_joins(pts, max_knots=12.0)
    assert out[0][2] == 0 and out[-1][2] == 4 * H


def test_a_leg_that_is_already_sailable_is_untouched():
    pts = [v(59.0, 10.0, 0), v(59.05, 10.0, 1 * H), v(59.1, 10.0, 2 * H)]
    assert M.smooth_joins(pts, max_knots=12.0) == pts


def test_positions_are_never_changed():
    pts = [v(59.0, 10.0, 0), v(59.1, 10.0, 60 * 1000), v(59.2, 10.0, 4 * H)]
    out = M.smooth_joins(pts, max_knots=12.0)
    assert [p[:2] for p in out] == [p[:2] for p in pts]


def test_times_stay_strictly_increasing():
    ## Including the inversion case: a later point carrying an earlier time, which is what
    ## two overlapping slice windows actually produce.
    pts = [v(59.0, 10.0, 0), v(59.02, 10.0, 3 * H), v(59.04, 10.0, 1 * H), v(59.2, 10.0, 6 * H)]
    ts = [p[2] for p in M.smooth_joins(pts, max_knots=12.0)]
    assert ts == sorted(ts) and len(set(ts)) == len(ts)


def test_a_leg_too_short_to_smooth_is_returned_unchanged():
    assert M.smooth_joins([v(59.0, 10.0, 0)], max_knots=12.0) == [v(59.0, 10.0, 0)]


def test_a_window_that_cannot_be_fixed_still_terminates():
    ## The bug this caught: if the two anchors are themselves too close in time for the
    ## distance between them, redistributing cannot make the edge sailable, so the loop
    ## re-times the same window forever. It must give up and leave the window alone.
    ## It hung on the real 2024-04-03 leg.
    pts = [v(59.0, 10.0, 0), v(59.5, 10.0, 1000), v(60.0, 10.0, 2000)]
    out = M.smooth_joins(pts, max_knots=12.0)          # must return, not hang
    assert len(out) == 3
    assert [p[2] for p in out] == sorted(p[2] for p in out)


## --------------------------------------------- when time order disagrees with track order
##
## The residual 2024-04-03 defect. Two adjacent slices of `Track 4 s88` carry assigned time
## windows that overlap, so sorting the merged leg by time interleaves them and the path
## ping-pongs: 20:30:29 from ...971575, 20:32:45 from ...971576, 20:34:57 from ...971575
## again. Redistributing time inside that window cannot help, because the *order* is wrong
## rather than the spacing.
##
## The repair reassigns the existing timestamps so that time order follows the segment's own
## point order. No timestamp is invented and none is discarded - they are the same times, on
## the right vertices.

SEG = [(59.0, 10.0), (59.1, 10.0), (59.2, 10.0), (59.3, 10.0)]


def test_a_ping_pong_is_put_back_into_track_order():
    ## Positions run 59.0, 59.2, 59.1 - i.e. segment order 0, 2, 1 - with ascending times.
    pts = [v(59.0, 10.0, 0), v(59.2, 10.0, 1 * H), v(59.1, 10.0, 2 * H)]
    out = M.reorder_times_by_segment(pts, SEG)
    byseg = sorted(out, key=lambda p: p[0])
    assert [p[2] for p in byseg] == sorted(p[2] for p in byseg)


def test_the_set_of_timestamps_is_preserved():
    pts = [v(59.0, 10.0, 0), v(59.2, 10.0, 1 * H), v(59.1, 10.0, 2 * H)]
    out = M.reorder_times_by_segment(pts, SEG)
    assert sorted(p[2] for p in out) == [0, 1 * H, 2 * H]


def test_points_already_in_order_are_unchanged():
    pts = [v(59.0, 10.0, 0), v(59.1, 10.0, 1 * H), v(59.2, 10.0, 2 * H)]
    assert M.reorder_times_by_segment(pts, SEG) == pts


def test_points_off_the_segment_keep_their_times():
    ## Tracker vertices nowhere near the plotter segment must not be dragged into its order.
    pts = [v(59.0, 10.0, 0), v(40.0, 20.0, 1 * H), v(59.1, 10.0, 2 * H)]
    out = M.reorder_times_by_segment(pts, SEG, tol_m=200)
    off = [p for p in out if p[0] == 40.0][0]
    assert off[2] == 1 * H


def test_an_empty_segment_changes_nothing():
    pts = [v(59.0, 10.0, 0), v(59.2, 10.0, 1 * H)]
    assert M.reorder_times_by_segment(pts, []) == pts


## ------------------------------------- two sources, one instant: the plotter's position wins
##
## The last 2024-04-03 defect. At 13:40:05 the tracker and the chartplotter both record a
## position, 0.11 nm apart - which is just the difference in their precision. Keeping both
## puts a 200 m wobble in the line and reads as 18.9 kn across it. The precedence rule in
## ../SOURCES.md settles it: the plotter carries the better position, so the tracker's vertex
## for that instant adds nothing.


def test_two_sources_at_one_instant_collapse_to_the_plotter():
    plotter = [v(59.0000, 10.0, 1 * H)]
    tracker = [v(59.0030, 10.0, 1 * H)]          # ~200 m away, same instant
    out = M.collect([plotter, tracker], 0, 10 * H, same_place_m=400)
    assert len(out) == 1
    assert out[0][0] == 59.0000                  # the plotter's, because it is listed first


def test_the_widened_tolerance_does_not_merge_different_instants():
    a = [v(59.0000, 10.0, 1 * H)]
    b = [v(59.0030, 10.0, 2 * H)]
    assert len(M.collect([a, b], 0, 10 * H, same_place_m=400)) == 2


def test_a_genuinely_distant_pair_at_one_instant_is_kept():
    ## Two records a mile apart at the same instant is a contradiction to surface, not to
    ## quietly drop.
    a = [v(59.00, 10.0, 1 * H)]
    b = [v(59.05, 10.0, 1 * H)]
    assert len(M.collect([a, b], 0, 10 * H, same_place_m=400)) == 2
