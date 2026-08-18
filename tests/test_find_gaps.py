"""Tests for which source segments the gap scan actually looks at.

Segment indices are **file-local**. The hand-cropped delivery files are excerpts of the
plotter's own `Track 1`, and each one renumbers its segments from zero, so `Track 1 s0`
names a different stretch of water in every one of the nine files that carries it. Keyed on
`(name, si)` the scan kept whichever file `sorted()` reached first and silently dropped the
rest — 459 of 1244 segments, of which 426 really were duplicates and about 33 were not.

Dropping the duplicates is still necessary: `france-etc.gpx` and `raymarine_rest.gpx` are
near-copies of one export, and counting their shared segments twice would inflate every
figure. So identity has to come from the **points**, not from the index.
"""

import datetime

from boattracker.nfl import find_gaps as FG

A = [(59.0, 10.0), (59.1, 10.0), (59.2, 10.0)]
B = [(58.0, 11.0), (58.1, 11.0), (58.2, 11.0)]


def test_the_same_points_under_the_same_index_are_one_segment():
    ## france-etc.gpx and raymarine_rest.gpx are near-copies of one export.
    segs = [('france-etc.gpx', 'Track 1', 0, A), ('raymarine_rest.gpx', 'Track 1', 0, A)]
    assert len(FG.dedupe(segs)) == 1


def test_different_points_under_the_same_index_are_two_segments():
    ## The bug. `Poland1.gpx` s0 and `benelux.gpx` s0 are different water and the old key
    ## could not tell them apart.
    segs = [('Poland1.gpx', 'Track 1', 0, A), ('benelux.gpx', 'Track 1', 0, B)]
    assert len(FG.dedupe(segs)) == 2


def test_the_same_points_in_one_file_under_different_indices_are_one_segment():
    ## Identity is the water, not the numbering, in both directions.
    segs = [('france-etc.gpx', 'Track 1', 3, A), ('france-etc.gpx', 'Track 1', 9, A)]
    assert len(FG.dedupe(segs)) == 1


def test_dedupe_keeps_the_first_occurrence_and_its_file():
    segs = [('benelux.gpx', 'Track 1', 0, A), ('raymarine_rest.gpx', 'Track 1', 0, A)]
    assert FG.dedupe(segs) == [('benelux.gpx', 'Track 1', 0, A)]


def test_the_test_fixture_is_not_read_as_survey_data():
    ## `test_raymarine.gpx` is the one .gpx `.gitignore` keeps, precisely because the tests
    ## need it. It was contributing four `Track 1` segments to real gap figures.
    assert not FG.is_survey_file('test_raymarine.gpx')
    assert not FG.is_survey_file('nfl-2024-04-03-track4s88-238.gpx')
    assert FG.is_survey_file('benelux.gpx')
    assert FG.is_survey_file('TracksA.gpx')


## ------------------------------------------- naming a track must not switch dating off
##
## `source_segments` read `if window and not tracks and not TD.overlaps(...)`, so passing
## `--tracks` opted out of the date filter entirely and a segment from any month of that
## track became eligible. That is how slices of `Track 4 s69` and `s71`, months away, were
## offered to fill gaps in the 2024-04-03 leg — only a geometric plausibility check caught
## them. Naming a track should *narrow* the search, never widen the dates.


def test_a_named_track_outside_the_window_is_still_excluded(monkeypatch):
    monkeypatch.setattr(FG.TD, 'overlaps', lambda name, lo, hi: False)
    assert not FG.eligible('Track 4', ['Track 4'], ('2024-04-01', '2024-04-30'))


def test_a_named_track_inside_the_window_is_kept(monkeypatch):
    monkeypatch.setattr(FG.TD, 'overlaps', lambda name, lo, hi: True)
    assert FG.eligible('Track 4', ['Track 4'], ('2024-04-01', '2024-04-30'))


def test_a_track_not_named_is_excluded_whatever_its_dates(monkeypatch):
    monkeypatch.setattr(FG.TD, 'overlaps', lambda name, lo, hi: True)
    assert not FG.eligible('Track 7', ['Track 4'], ('2024-04-01', '2024-04-30'))


def test_without_a_window_dating_cannot_exclude_anything(monkeypatch):
    ## No window means the caller has not said when it is interested in.
    monkeypatch.setattr(FG.TD, 'overlaps', lambda name, lo, hi: False)
    assert FG.eligible('Track 4', ['Track 4'], None)


def test_without_named_tracks_the_date_filter_still_applies(monkeypatch):
    monkeypatch.setattr(FG.TD, 'overlaps', lambda name, lo, hi: False)
    assert not FG.eligible('Track 4', None, ('2024-04-01', '2024-04-30'))


## ------------------------------------------- dating has to reach the segment, not the track
##
## Closing the `--tracks` hole above is not enough on its own: `overlaps()` answers for a
## whole track, and `Track 4` spans 2023-12 to 2024-05, so every one of its segments passes a
## filter set to a single April day. The slices that were wrongly offered for 2024-04-03 came
## from *the same track*, months apart. `track_dates.segment_window()` can bracket a single
## segment, so that is what has to be asked.


def test_segment_dating_is_opt_in():
    ## The gap scans keep their old accounting; only the callers choosing slices to upload
    ## ask for it. Applying it everywhere moved the 2023 total by 65 nm on an unchanged
    ## snapshot, through the dedupe interaction described in `segment_eligible`.
    import inspect
    sig = inspect.signature(FG.source_segments)
    assert sig.parameters['strict_dates'].default is False


def test_a_segment_dated_to_another_month_is_excluded(monkeypatch):
    monkeypatch.setattr(FG.TD, 'segment_window',
                        lambda name, si, **kw: (datetime.date(2024, 3, 1),
                                                datetime.date(2024, 3, 20)))
    assert not FG.segment_eligible('Track 4', 69, ('2024-04-02', '2024-04-03'))


def test_a_segment_dated_inside_the_window_is_kept(monkeypatch):
    monkeypatch.setattr(FG.TD, 'segment_window',
                        lambda name, si, **kw: (datetime.date(2024, 4, 1),
                                                datetime.date(2024, 4, 10)))
    assert FG.segment_eligible('Track 4', 88, ('2024-04-02', '2024-04-03'))


def test_an_undated_segment_is_allowed(monkeypatch):
    ## Unknown must never mean excluded — that is the rule the whole date map runs on.
    monkeypatch.setattr(FG.TD, 'segment_window', lambda name, si, **kw: None)
    assert FG.segment_eligible('Track 4', 69, ('2024-04-02', '2024-04-03'))


def test_no_window_means_no_segment_filtering(monkeypatch):
    monkeypatch.setattr(FG.TD, 'segment_window',
                        lambda name, si, **kw: (datetime.date(2020, 1, 1),
                                                datetime.date(2020, 1, 2)))
    assert FG.segment_eligible('Track 4', 69, None)


def test_drop_off_planet_removes_a_track_s_peru_segments():
    """The diary, 2026-08-07: the plotter 'decided we were in Peru, cruising in a
    circle in 109 knots'. Those segments pass the lat/lon range check, so without
    this guard they are reported as missing track for ever."""
    from boattracker.nfl.find_gaps import drop_off_planet
    black_sea = [[(43.3 + i / 100, 28.4)] * 2 for i in range(4)]
    peru = [[(-12.04, -77.05)] * 2]
    segs = [("Tracks.gpx", "Track 65", i, p)
            for i, p in enumerate(black_sea + peru)]
    kept = drop_off_planet(segs)
    assert [s[2] for s in kept] == [0, 1, 2, 3]


def test_drop_off_planet_keeps_a_track_that_is_merely_long():
    """Judged per track against that track's own median, so a real Mediterranean
    season spanning 2000 nm survives; measuring against the whole corpus would not."""
    from boattracker.nfl.find_gaps import drop_off_planet
    segs = [("france-etc.gpx", "Med 2023", i, [(37.0 + i * 2, -1.0 + i * 5)] * 2)
            for i in range(5)]
    assert len(drop_off_planet(segs)) == 5


def test_drop_off_planet_will_not_judge_a_track_of_two():
    """Two segments have no majority, so neither can be called the outlier."""
    from boattracker.nfl.find_gaps import drop_off_planet
    segs = [("Tracks.gpx", "Track 65", 0, [(43.3, 28.4)] * 2),
            ("Tracks.gpx", "Track 65", 1, [(-12.04, -77.05)] * 2)]
    assert len(drop_off_planet(segs)) == 2


## `source_segments()` reads the corpus off disk, and until 2026-08-17 nothing here
## exercised that path — every test above stubs the segment list or tests `eligible()`
## alone. The gap was not theoretical: extracting the file helpers into
## `boattracker.files` put a module named `files` in scope, `source_segments()` has a
## keyword parameter of the same name, and the local shadowed the module. Ruff saw
## nothing, all 329 tests passed, and the first real scan died with
## `'list' object has no attribute 'read_text'`.

def gpx(name, points):
    pts = '\n'.join(f'<trkpt lon="{lo}" lat="{la}"></trkpt>' for la, lo in points)
    return f'<gpx><trk><name>{name}</name><trkseg>{pts}</trkseg></trk></gpx>'


def test_source_segments_reads_a_track_off_disk(tmp_path, monkeypatch):
    ## 25 points running a bit over a kilometre north - past both the 20-point floor and
    ## the 0.25 nm excursion floor.
    points = [(59.90 + i * 0.0005, 10.55) for i in range(25)]
    (tmp_path / 'Tracks.gpx').write_text(gpx('Track 9', points))
    monkeypatch.setattr(FG, 'T', str(tmp_path))

    segs = FG.source_segments()

    assert len(segs) == 1
    fn, name, si, p = segs[0]
    assert (fn, name, si) == ('Tracks.gpx', 'Track 9', 0)
    assert len(p) == 25
    assert p[0] == (59.90, 10.55)


def test_source_segments_skips_a_segment_that_never_moves(tmp_path, monkeypatch):
    """A boat sitting at a berth is not a segment to compare coverage against."""
    (tmp_path / 'Tracks.gpx').write_text(gpx('Track 9', [(59.90, 10.55)] * 25))
    monkeypatch.setattr(FG, 'T', str(tmp_path))

    assert FG.source_segments() == []
