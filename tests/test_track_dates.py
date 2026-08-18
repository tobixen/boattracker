"""Tests for the date map, and for one disagreement inside it.

`overlaps()` and `segment_window()` both need a fallback range for a track, and until
2026-08-12 they chose it in opposite orders. `overlaps()` prefers the year in a named
track's own name; `segment_window()` preferred the range derived from `nfl-export/`
filenames, which for a named track covers only the handful of segments that happen to have
been exported. The consequence was measured, not theoretical: `Med 2023` s94, s98 and s101
are November and December legs — their endpoints coincide with the journey's own
2023-11-24, 2023-11-27 and 2023-11-30 fixes — and every one of them was bracketed to
October, so `find_gaps.py` compared them against the wrong weeks of journey data.
"""

import datetime

from boattracker.nfl import track_dates as td


def stub(monkeypatch, exported, track_range):
    """Pin both sources `segment_window()` consults, keyed for 'Med 2023'."""
    monkeypatch.setattr(td, 'segment_ranges',
                        lambda: {('med2023', si): d for si, d in exported.items()})
    monkeypatch.setattr(td, 'ranges', lambda: {'med2023': track_range})


D = datetime.date


def test_a_named_track_segment_past_its_last_export_reaches_the_year_end(monkeypatch):
    ## s94 has no dated segment above it. The upper bound must come from the year in the
    ## name, not from the last file that happened to be exported.
    stub(monkeypatch, {80: D(2023, 10, 9)}, (D(2023, 6, 10), D(2023, 10, 16)))
    lo, hi = td.segment_window('Med 2023', 94)
    assert hi >= D(2023, 11, 24), hi


def test_a_named_track_segment_before_its_first_export_reaches_the_year_start(monkeypatch):
    stub(monkeypatch, {80: D(2023, 10, 9)}, (D(2023, 6, 10), D(2023, 10, 16)))
    lo, hi = td.segment_window('Med 2023', 3)
    assert lo <= D(2023, 1, 1), lo


def test_interpolation_still_wins_where_there_are_dated_segments_either_side(monkeypatch):
    ## The whole point of `segment_window` is the tight bracket. Widening the *fallback*
    ## must not widen the interpolated case, or the filter stops excluding anything.
    stub(monkeypatch, {90: D(2023, 10, 9), 96: D(2023, 10, 20)},
         (D(2023, 6, 10), D(2023, 10, 16)))
    lo, hi = td.segment_window('Med 2023', 94, pad_days=4)
    assert lo == D(2023, 10, 5) and hi == D(2023, 10, 24)


def test_a_numbered_track_is_unaffected(monkeypatch):
    ## Numbered tracks carry no year, so there is nothing to fall back to and the exported
    ## range must still bound them — that is what stops a 2026 track bridging a 2024 gap.
    ## Two dated segments, because one is not enough to interpolate between (below).
    monkeypatch.setattr(td, 'segment_ranges',
                        lambda: {('4', 8): D(2024, 2, 1), ('4', 10): D(2024, 3, 1)})
    monkeypatch.setattr(td, 'ranges', lambda: {'4': (D(2024, 1, 1), D(2024, 4, 1))})
    lo, hi = td.segment_window('Track 4', 50, pad_days=0)
    assert hi == D(2024, 4, 1)


def test_overlaps_and_segment_window_agree_on_a_named_track(monkeypatch):
    ## The bug was the two disagreeing. Pin that they do not.
    stub(monkeypatch, {80: D(2023, 10, 9)}, (D(2023, 6, 10), D(2023, 10, 16)))
    lo, hi = td.segment_window('Med 2023', 94)
    assert td.overlaps('Med 2023', lo, hi)
    assert td.overlaps('Med 2023', D(2023, 11, 24), D(2023, 11, 24))


## ------------------------------------------------- when there is nothing to interpolate
##
## `Track 1` holds 182 segments across nine crop files, spanning the whole 2022 delivery and
## into 2023, and exactly **one** of them is dated by an export. Interpolating from that one
## gave every segment the fortnight 2023-05-27 .. 06-07 — so the 268 nm Biscay crossing, a
## 2022-09 leg that is on the journey, was compared against a fortnight of 2023 lines and
## reported 100% missing. A fabricated window is worse than no window: this filter exists to
## drop candidates provably from another season, not to assert knowledge the map lacks.


def test_a_numbered_track_with_one_dated_segment_has_no_window(monkeypatch):
    monkeypatch.setattr(td, 'segment_ranges', lambda: {('1', 40): D(2023, 6, 3)})
    monkeypatch.setattr(td, 'ranges', lambda: {'1': (D(2023, 5, 31), D(2023, 12, 21))})
    assert td.segment_window('Track 1', 21) is None


def test_two_dated_segments_are_enough_to_interpolate(monkeypatch):
    ## The bar is "something on each side to interpolate between", not "a lot of data".
    monkeypatch.setattr(td, 'segment_ranges',
                        lambda: {('1', 10): D(2023, 6, 3), ('1', 40): D(2023, 7, 3)})
    monkeypatch.setattr(td, 'ranges', lambda: {'1': (D(2023, 5, 31), D(2023, 12, 21))})
    assert td.segment_window('Track 1', 21) is not None


def test_a_named_track_with_one_dated_segment_still_has_its_year(monkeypatch):
    ## The year in the name is real information and survives the thinness test.
    monkeypatch.setattr(td, 'segment_ranges', lambda: {('med2023', 40): D(2023, 6, 3)})
    monkeypatch.setattr(td, 'ranges', lambda: {'med2023': (D(2023, 6, 3), D(2023, 6, 3))})
    lo, hi = td.segment_window('Med 2023', 94)
    assert hi >= D(2023, 11, 24)


def test_a_thinly_dated_track_is_not_excluded_from_another_season(monkeypatch):
    ## The other half of the same rule. `overlaps()` gates which segments are considered at
    ## all, and on `ranges()['1']` it answered False for 2022 — so the whole 2022 delivery
    ## was dropped before coverage was even measured, and the scan reported "0 source
    ## segments" for a season with 182 of them. One dated segment out of 182 does not make a
    ## track "provably from another season", which is the only thing this filter is for.
    monkeypatch.setattr(td, 'segment_ranges', lambda: {('1', 40): D(2023, 6, 3)})
    monkeypatch.setattr(td, 'ranges', lambda: {'1': (D(2023, 5, 31), D(2023, 12, 21))})
    assert td.overlaps('Track 1', D(2022, 1, 1), D(2022, 12, 31))


def test_a_well_dated_track_is_still_excluded_from_another_season(monkeypatch):
    ## And the filter must still do its job, or a 2026 track bridges a 2024 gap.
    monkeypatch.setattr(td, 'segment_ranges',
                        lambda: {('4', 8): D(2024, 2, 1), ('4', 10): D(2024, 3, 1)})
    monkeypatch.setattr(td, 'ranges', lambda: {'4': (D(2024, 1, 1), D(2024, 4, 1))})
    assert not td.overlaps('Track 4', D(2026, 1, 1), D(2026, 12, 31))
    assert td.overlaps('Track 4', D(2024, 2, 1), D(2024, 2, 28))


def test_norm_ignores_the_plotter_s_alphabetic_suffixes():
    """'Track 64Xxx' and 'Track 67W' are the owner's annotations on the plotter's
    counter, not separate tracks. Matching only a trailing 'P' left both permanently
    undated, so every gap scan measured their water against the whole journey."""
    from boattracker.nfl.track_dates import _norm
    assert _norm("Track 64Xxx") == "64"
    assert _norm("Track 67W") == "67"
    assert _norm("Track 26P") == "26"
    assert _norm("Track 57.202509") == "57_202509"
    assert _norm("Med 2023") == "med2023"


def test_export_filename_parser_reads_a_suffixed_track():
    import re
    pat = re.compile(r'(?:^|-)t(?:rack)?(?:q-t)?(\d+(?:_\d+)?)[a-z]*s(\d+)')
    assert pat.search("nfl-2026-08-06-track64xxxs2-kaliakra.gpx").groups() == ("64", "2")
    assert pat.search("nfl-2026-08-12-track67ws4-ggyc.gpx").groups() == ("67", "4")
    assert pat.search("nfl-2024-02-24-track4s58-28.gpx").groups() == ("4", "58")
