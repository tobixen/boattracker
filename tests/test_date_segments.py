"""Tests for the plotter segment ledger.

The ledger is the one place a segment's date is written down, so the tests that matter most
are the ones about not losing what is in it: a row the owner dated by hand survives every
rerun, and so does every note. Then the precedence: the phone, which has the time, beats a
date borrowed from an export file name, which is how the Istanbul 2025-08-28 approach got
filed under 08-29.
"""

from datetime import UTC, date, datetime, timedelta

from boattracker.nfl import date_segments as ds
from boattracker.nfl.omaps_export import Fix
from boattracker.nfl.timestamp_segments import Segment


def line(a, b, n=200):
    return [(a[0] + (b[0] - a[0]) * k / (n - 1), a[1] + (b[1] - a[1]) * k / (n - 1)) for k in range(n)]


A, B = (41.000, 28.900), (41.000, 28.990)  # 4 nm east-west off Istanbul


def phone_along(pts, t0, step=10):
    return [Fix(la, lo, t0 + timedelta(seconds=step * k)) for k, (la, lo) in enumerate(pts)]


def seg(track="Track 52", idx=1, pts=None):
    return Segment(track, idx, pts or line(A, B), "guid-%s-%d" % (track, idx))


T0 = datetime(2025, 8, 28, 14, 0, tzinfo=UTC)


def test_the_phone_dates_a_segment_and_beats_the_export_name():
    s = seg()
    phone = phone_along(s.points, T0)
    row = ds.propose(s, ds.Sources(phone=phone, export_date=date(2025, 8, 29)),
                     window=(date(2025, 8, 25), date(2025, 9, 2)))
    assert row.date == "2025-08-28"
    assert row.dated_by == "phone"
    assert row.t0.startswith("2025-08-28T14:00") and row.i0 == 0
    assert "export 2025-08-29" in row.check


def test_the_export_name_is_a_last_resort_and_says_so():
    row = ds.propose(seg(), ds.Sources(export_date=date(2025, 8, 29)), window=None)
    assert (row.date, row.dated_by, row.t0) == ("2025-08-29", "export", "")


def test_a_journey_fix_at_the_segment_end_dates_it():
    s = seg()
    fixes = [(*B, (T0 + timedelta(hours=3)).timestamp()), (*A, (T0 - timedelta(days=30)).timestamp())]
    row = ds.propose(s, ds.Sources(fixes=fixes), window=(date(2025, 8, 25), date(2025, 9, 2)))
    assert (row.date, row.dated_by) == ("2025-08-28", "fix")


def test_two_fixes_at_the_end_within_the_window_date_nothing():
    # the boat came back to the same anchorage: the fix cannot say which visit this was
    s = seg()
    fixes = [(*B, (T0 + timedelta(hours=3)).timestamp()), (*B, (T0 + timedelta(days=2)).timestamp())]
    row = ds.propose(s, ds.Sources(fixes=fixes), window=(date(2025, 8, 25), date(2025, 9, 2)))
    assert row.date == ""
    assert "2 fixes" in row.check


def test_a_phone_match_outside_the_window_is_not_taken():
    s = seg()
    phone = phone_along(s.points, T0 + timedelta(days=60))  # the same water, two months on
    row = ds.propose(s, ds.Sources(phone=phone), window=(date(2025, 8, 25), date(2025, 9, 2)))
    assert row.dated_by != "phone"


def test_a_diary_heading_naming_the_end_place_dates_it():
    s = seg()
    places = [("Cerrapasa, Istanbul", *B)]
    heads = [("2025-08-27", ["Avcılar", "Büyükçekmece"]), ("2025-08-28", ["Büyükçekmece", "Cerrapasa, Istanbul"])]
    row = ds.propose(s, ds.Sources(heads=heads, places=places), window=(date(2025, 8, 25), date(2025, 9, 2)))
    assert (row.date, row.dated_by) == ("2025-08-28", "diary")


def test_an_owner_row_survives_a_rerun_and_every_note_is_kept(tmp_path):
    path = tmp_path / "plotter-segments.tsv"
    old = {("Track 52", 1): ds.Row("Track 52", 1, date="2025-08-28", dated_by="owner", notes="checked on the chart"),
           ("Track 52", 2): ds.Row("Track 52", 2, date="2025-08-29", dated_by="phone", notes="keep me")}
    ds.write_ledger(path, old)
    new = {("Track 52", 1): ds.Row("Track 52", 1, date="2025-08-29", dated_by="export"),
           ("Track 52", 2): ds.Row("Track 52", 2, date="2025-08-30", dated_by="fix")}
    merged = ds.merge(ds.read_ledger(path), new)
    assert merged[("Track 52", 1)].date == "2025-08-28"
    assert merged[("Track 52", 1)].dated_by == "owner"
    assert merged[("Track 52", 2)].date == "2025-08-30"
    assert merged[("Track 52", 2)].notes == "keep me"


def test_the_ledger_round_trips(tmp_path):
    path = tmp_path / "l.tsv"
    rows = {("Track 7", 3): ds.Row("Track 7", 3, guid="g", points=12, date="2024-05-01",
                                   notes="tab\tand newline\nare flattened")}
    ds.write_ledger(path, rows)
    back = ds.read_ledger(path)
    assert back[("Track 7", 3)].points == 12
    assert back[("Track 7", 3)].notes == "tab and newline are flattened"


def test_copies_of_one_segment_across_exports_keep_the_longest():
    short, longer = seg(pts=line(A, B, 50)), seg(pts=line(A, B, 300))
    got = ds.dedupe([("TracksA.gpx", short), ("Tracks.gpx", longer)])
    assert [(f, len(s.points)) for f, s in got] == [("Tracks.gpx", 300)]


def test_segments_are_ordered_by_track_number_then_index():
    segs = [seg("Track 67W", 0), seg("Track 8", 2), seg("Track 8", 10), seg("Track 52", 1)]
    assert [(s.track, s.idx) for s in sorted(segs, key=ds.order_key)] == [
        ("Track 8", 2), ("Track 8", 10), ("Track 52", 1), ("Track 67W", 0)]


def test_a_date_out_of_plotter_order_is_flagged():
    rows = [ds.Row("Track 52", 0, date="2025-08-28"), ds.Row("Track 52", 1, date="2025-08-27"),
            ds.Row("Track 52", 2, date="2025-08-29")]
    ds.check_order(rows)
    assert "out of order" in rows[1].check
    assert rows[0].check == rows[2].check == ""


def test_the_heaviest_ordered_chain_wins_and_the_rest_are_cleared():
    # a short harbour segment matched to a revisit weeks off breaks plotter order; the
    # phone-dated neighbours either side outweigh it
    rows = [ds.Row("Track 69", 0, date="2026-11-08", dated_by="phone", nm=5),
            ds.Row("Track 69", 1, date="2026-10-31", dated_by="phone", nm=0.3),
            ds.Row("Track 69", 2, date="2026-11-09", dated_by="phone", nm=6),
            ds.Row("Track 69", 3, date="2026-11-10", dated_by="export")]
    ds.keep_ordered(rows)
    assert [r.date for r in rows] == ["2026-11-08", "", "2026-11-09", "2026-11-10"]
    assert "2026-10-31 by phone, out of plotter order" in rows[1].check


def test_an_owner_date_is_never_cleared():
    rows = [ds.Row("Track 8", 0, date="2025-03-01", dated_by="phone", nm=5),
            ds.Row("Track 8", 1, date="2025-02-25", dated_by="owner"),
            ds.Row("Track 8", 2, date="2025-03-02", dated_by="phone", nm=5)]
    ds.keep_ordered(rows)
    assert rows[1].date == "2025-02-25"


def test_a_phone_match_is_taken_only_inside_the_window_it_is_given():
    s = seg("Track 69", 1)
    phone = (phone_along(s.points, datetime(2026, 10, 31, 9, 0, tzinfo=UTC))
             + phone_along(s.points, datetime(2026, 11, 8, 15, 0, tzinfo=UTC)))
    row = ds.propose(s, ds.Sources(phone=sorted(phone)), window=(date(2026, 11, 8), date(2026, 11, 9)))
    assert (row.date, row.dated_by) == ("2026-11-08", "phone")


def test_a_phone_match_spanning_a_revisit_keeps_only_the_biggest_cluster():
    # 2026-11-03: the first two thirds matched on the day, the rest on a revisit six days on
    s = seg("Track 71", 5)
    day = phone_along(s.points[:140], datetime(2026, 11, 3, 16, 0, tzinfo=UTC))
    later = phone_along(s.points[140:], datetime(2026, 11, 9, 12, 0, tzinfo=UTC))
    row = ds.propose(s, ds.Sources(phone=day + later), window=(date(2026, 11, 1), date(2026, 11, 12)))
    assert row.date == "2026-11-03"
    assert row.t1.startswith("2026-11-03")


C, D_ = (41.000, 29.080), (41.000, 29.170)


def build(segs, phone, old=None, monkeypatch=None):
    monkeypatch.setattr(ds.track_dates, "segment_ranges", lambda: {})
    monkeypatch.setattr(ds.track_dates, "segment_window", lambda *a, **k: None)
    found = [("Tracks.gpx", s) for s in segs]
    return ds.build(found, ds.Sources(phone=sorted(phone)), old or {})


def test_an_owner_row_overrules_its_neighbours_in_build(monkeypatch):
    # 2026-11-03/04: Track 72 s0's phone match was the 11-09 trip over the same water; the
    # owner's 11-04 on s1 has to clear it, and not just survive beside it
    s0, s1 = seg("Track 72", 0, line(A, B)), seg("Track 72", 1, line(B, C))
    phone = phone_along(s0.points, datetime(2026, 11, 9, 15, 0, tzinfo=UTC))
    old = {("Track 72", 1): ds.Row("Track 72", 1, date="2026-11-04", dated_by="owner")}
    got = build([s0, s1], phone, old, monkeypatch)
    assert got[("Track 72", 1)].date == "2026-11-04"
    assert got[("Track 72", 0)].date == ""
    assert "2026-11-09 by phone, out of plotter order" in got[("Track 72", 0)].check


def test_a_segment_between_two_of_one_day_is_that_day(monkeypatch):
    # 2025-09-06: Track 56 s3 lies between s2 and s4, both of that day; nothing else dates it
    far = ((41.1, 28.9), (41.1, 28.99))   # off the phone's track, so only the order dates it
    s0, s1, s2 = seg("Track 56", 2, line(A, B)), seg("Track 56", 3, line(*far)), seg("Track 56", 4, line(C, D_))
    phone = (phone_along(s0.points, datetime(2025, 9, 6, 8, 0, tzinfo=UTC))
             + phone_along(s2.points, datetime(2025, 9, 6, 12, 0, tzinfo=UTC)))
    got = build([s0, s1, s2], phone, None, monkeypatch)
    assert (got[("Track 56", 3)].date, got[("Track 56", 3)].dated_by) == ("2025-09-06", "order")


def test_an_owner_row_without_a_date_stays_undated(monkeypatch):
    # Track 37 s2-s4: GPS spoofing, between two segments of 2025-07-26
    s0, s1, s2 = seg("Track 37", 1, line(A, B)), seg("Track 37", 2, line(B, C)), seg("Track 37", 5, line(C, D_))
    phone = (phone_along(s0.points, datetime(2025, 7, 26, 8, 0, tzinfo=UTC))
             + phone_along(s2.points, datetime(2025, 7, 26, 12, 0, tzinfo=UTC)))
    old = {("Track 37", 2): ds.Row("Track 37", 2, dated_by="owner", notes="spoofed")}
    got = build([s0, s1, s2], phone, old, monkeypatch)
    assert (got[("Track 37", 2)].date, got[("Track 37", 2)].dated_by) == ("", "owner")


def test_a_fix_in_the_small_hours_of_a_local_day_is_in_its_window():
    # Istanbul is UTC+3: 22:30 UTC on 08-28 is 01:30 on 08-29, inside a window of 08-29
    s = seg()
    t = datetime(2025, 8, 28, 22, 30, tzinfo=UTC)
    row = ds.propose(s, ds.Sources(fixes=[(*B, t.timestamp())]), window=(date(2025, 8, 29), date(2025, 8, 29)))
    assert (row.date, row.dated_by) == ("2025-08-29", "fix")
