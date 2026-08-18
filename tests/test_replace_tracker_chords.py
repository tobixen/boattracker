"""Tests for the check that stops the chord replacer re-uploading its own past work.

The trap, walked into on 2026-08-14: the tool asks whether plotter cover *exists* for a
tracker chord, and never whether that cover is **already on the journey**. It listed four
candidates whose plotter geometry had been uploaded months earlier — the "fragments" showing
up in the backtrack reports *are* its own previous output, e.g.
`nfl-export/nfl-2024-02-24-track4s58-28.gpx` is fix `6755398652971554`. Acting on that list
would have put a second copy of the same water on the journey.

The tracker's chord is still there and still wrong; what has to happen is that the chord goes,
not that the plotter track is sent again.
"""

from boattracker.nfl import replace_tracker_chords as R

## a slice running due north, roughly 0.6 nm between points
SLICE = [(59.00, 10.0), (59.01, 10.0), (59.02, 10.0), (59.03, 10.0)]


def test_a_slice_nothing_else_holds_is_not_on_the_journey():
    other = [[(58.00, 12.0), (58.01, 12.0)]]
    assert R.already_on_journey(SLICE, other) == 0.0


def test_a_slice_lying_under_an_existing_line_is_on_the_journey():
    assert R.already_on_journey(SLICE, [list(SLICE)]) == 100.0


def test_no_other_lines_at_all_is_not_on_the_journey():
    assert R.already_on_journey(SLICE, []) == 0.0


def test_half_covered_reads_as_about_half():
    ## Only the southern half is held elsewhere.
    other = [[(59.00, 10.0), (59.015, 10.0)]]
    pct = R.already_on_journey(SLICE, other)
    assert 30 < pct < 70, pct


def test_coverage_is_weighted_by_distance_not_by_edge_count():
    ## One long uncovered edge must outweigh several short covered ones, or a slice that is
    ## mostly missing reads as mostly present.
    sl = [(59.00, 10.0), (59.001, 10.0), (59.002, 10.0), (59.20, 10.0)]
    other = [[(59.00, 10.0), (59.002, 10.0)]]
    assert R.already_on_journey(sl, other) < 10


def test_the_repaired_fix_is_excluded_from_the_comparison():
    ## The tracker line being repaired must not count as cover for the slice that is meant
    ## to replace its chord - it would mark every candidate as already done.
    doc = {'geojson': {'features': [
        {'geometry': {'type': 'LineString', 'coordinates': [[10.0, 59.0], [10.0, 59.03]]},
         'properties': {'fixId': 111}},
        {'geometry': {'type': 'LineString', 'coordinates': [[12.0, 58.0], [12.0, 58.03]]},
         'properties': {'fixId': 222}},
    ]}}
    kept = R.journey_lines_except(doc, 111)
    assert len(kept) == 1
    assert R.already_on_journey(SLICE, kept) == 0.0


def test_a_slice_too_short_to_measure_is_not_claimed_as_covered():
    assert R.already_on_journey([(59.0, 10.0)], [[(59.0, 10.0), (59.01, 10.0)]]) == 0.0


## ------------------------------------------------- what makes a track worth replacing
##
## The owner's rule, 2026-08-14, and it replaces the deviation-based reasoning this module
## was written with: **a jump of more than a nautical mile between two consecutive vertices,
## where more precise data exists.** A gap that big is missing data. An 11 m deviation is
## not - that is GPS noise, and re-sending a track for it costs a message and buys nothing.


def test_a_jump_over_a_mile_is_worth_replacing():
    assert R.replaceable(4.29)
    assert R.replaceable(1.01)


def test_a_jump_under_a_mile_is_not():
    assert not R.replaceable(0.9)
    assert not R.replaceable(0.05)


def test_the_threshold_is_a_nautical_mile_by_default():
    assert R.MIN_JUMP_NM == 1.0


def test_the_threshold_can_be_raised_for_a_coarser_sweep():
    assert not R.replaceable(2.0, min_jump=5.0)
    assert R.replaceable(6.0, min_jump=5.0)


## --------------------------------------------- a short chord still deserves its plotter track
##
## `covering_slice` required at least 10 plotter points between the chord's two ends. On a
## coarse track — the 2023-24 crops run 400 to 1100 m between points — a 1 to 2 nm chord is
## three to six points, so the threshold refused every short chord on principle.
##
## Measured on the 2023-06-05 leg: 15 of its 17 chords over 1 nm are covered by `Track 1 s52`
## with the ends within 69 to 350 m and real times at both, and every one was refused for
## having 3 to 8 points between. That is 23.6 nm of real plotter detail withheld by an
## arbitrary count — and the owner's rule is that a jump over one nautical mile with better
## data available is worth replacing.


def test_a_short_slice_with_real_detail_is_accepted():
    ## Four points between the ends: a curve the straight chord does not have.
    seg = [(59.000, 10.0), (59.005, 10.02), (59.010, 10.03), (59.015, 10.02), (59.020, 10.0)]
    got = R.covering_slice([('f.gpx', 'Track 1', 52, seg)], (59.000, 10.0), (59.020, 10.0))
    assert got is not None
    assert len(got[4]) == 5


def test_a_two_point_slice_adds_nothing_and_is_refused():
    ## Both ends and nothing between is just the chord again.
    seg = [(59.0, 10.0), (59.02, 10.0)]
    assert R.covering_slice([('f.gpx', 'Track 1', 52, seg)], (59.0, 10.0), (59.02, 10.0)) is None


def test_the_minimum_is_a_couple_of_intermediate_points():
    assert R.MIN_SLICE_POINTS <= 4
