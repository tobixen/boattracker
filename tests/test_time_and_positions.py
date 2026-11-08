"""Tests for the diary's "Time and positions" sections.

The two that matter most are the rerun ones: the diary is hand-written text with generated
sections inside it, and a rerun over one month once dropped every generated section in the
file. And the per-leg mixing one, which is the reason the tool exists in this form - on
2026-11-02 a phone leg timed to the minute was thrown away because the other leg that day
was vague in the phone data.
"""

import datetime as D
import json

from boattracker.nfl import time_and_positions as tp

UTC = D.UTC


def ts(s):
    return D.datetime.fromisoformat(s).replace(tzinfo=UTC).timestamp()


def pt(t, lat, lon, src="nfl", lo=None, hi=None, stop=False):
    t = ts(t)
    return tp.Pt(t, lat, lon, src, ts(lo) if lo else t, ts(hi) if hi else t, stop)


DIARY = """# Chapter

## Monday 2026-11-02 - Sozopol - St Ivan - Sozopol

Text.

### Time and positions

*(Derived afterwards from x by `journey/archive/time_and_positions.py` - old marker.)*

* old line one

### Maintenance

* keep me

## Tuesday 2026-11-03

### Time and positions

*(Derived afterwards from x by `boattracker.nfl.time_and_positions` - outside the range.)*

* generated, not to be lost

## Wednesday 2026-11-04 - A - B

### Time and positions

*(Hand-maintained.)*

* hand line
"""


def test_a_rerun_replaces_old_marker_sections_in_range():
    out = tp.replace_sections(DIARY, {"2026-11-02": (["phone"], ["* new line"])},
                              "2026-11-02", "2026-11-02")
    assert "* new line" in out
    assert "old line one" not in out
    assert "* keep me" in out


def test_a_rerun_over_a_narrow_range_keeps_sections_outside_it():
    out = tp.replace_sections(DIARY, {"2026-11-02": (["phone"], ["* new line"])},
                              "2026-11-02", "2026-11-02")
    assert "generated, not to be lost" in out


def test_hand_maintained_sections_are_never_touched():
    out = tp.replace_sections(DIARY, {"2026-11-04": (["nfl"], ["* generated"])},
                              "2026-11-01", "2026-11-30")
    assert "* hand line" in out
    assert "* generated" not in out


def test_hand_maintained_days_are_found():
    assert tp.hand_maintained(DIARY) == {"2026-11-04"}


def test_the_diary_day_is_the_local_day():
    # Bulgaria in winter is UTC+2: the day starts at 22:00 UTC the evening before, not
    # 21:00, which was the hardcoded summer offset.
    d0, d1 = tp.day_window("2026-11-07", "Europe/Sofia")
    assert d0 == ts("2026-11-06T22:00")
    assert d1 == ts("2026-11-07T22:00")
    d0, _ = tp.day_window("2025-03-05", "Europe/Istanbul")
    assert d0 == ts("2025-03-04T21:00")


def test_the_day_zone_is_taken_from_land_not_from_a_nautical_zone():
    # Mid-Black Sea is Etc/GMT-2 in the boundary data, with no summer time; the boat's
    # last position near land says what clock the diary was written by.
    pts = [pt("2025-08-30T06:00", 41.36745, 28.93828), pt("2025-08-31T06:00", 42.29822, 28.55719)]
    assert tp.day_zone(pts, ts("2025-08-31T09:00")) == "Europe/Istanbul"
    assert tp.day_zone([], ts("2025-08-31T09:00")) == "UTC"


def test_a_shutter_clock_in_any_whole_hour_zone_passes():
    g = ts("2021-05-20T10:00:00")
    assert tp.clocks_agree(g + 3600, g)      # Norway, winter
    assert tp.clocks_agree(g + 3 * 3600 + 30, g)
    assert tp.clocks_agree(g, g)


def test_a_stale_gps_fix_is_refused():
    g = ts("2021-05-20T10:00:00")
    assert not tp.clocks_agree(g + 2 * 3600 + 1500, g)
    assert not tp.clocks_agree(g + 20 * 3600, g)


def photo_dir(tmp_path, records, entries):
    (tmp_path / "exif-index.json").write_text(json.dumps(records))
    (tmp_path / "manual-locations.json").write_text(json.dumps(entries))
    return str(tmp_path)


def rec(path, time, gps_time, lat=43.2, lon=27.9):
    return {"path": path, "time": time, "gps_time": gps_time, "lat": lat, "lon": lon, "fix": "gps"}


def test_only_a_path_entry_marks_a_photograph_as_a_stop(tmp_path):
    d = photo_dir(tmp_path,
                  [rec("a.jpg", "2021-05-13T12:00:00", "2021:05:13 10:00:00Z"),
                   rec("b.jpg", "2021-05-13T13:00:00", "2021:05:13 11:00:00Z"),
                   rec("c.jpg", "2021-05-14T13:00:00", "2021:05:14 11:00:00Z")],
                  [{"day": "2021-05-13", "ashore": False, "note": "under way"},
                   {"path": "c.jpg", "ashore": False}])
    marks = {p.t: p.stop for p in tp.photo_points(d)}
    assert marks[ts("2021-05-13T10:00")] is False
    assert marks[ts("2021-05-13T11:00")] is False
    assert marks[ts("2021-05-14T11:00")] == 2


def test_photographs_ashore_are_left_out(tmp_path):
    d = photo_dir(tmp_path, [rec("a.jpg", "2021-05-13T12:00:00", "2021:05:13 10:00:00Z")],
                  [{"path": "a.jpg", "ashore": True}])
    assert tp.photo_points(d) == []


# Two moves on one day: the phone has the first exactly and the second only vaguely, the
# journey both vaguely. 2026-11-02, Sozopol -> St Ivan -> Nessebar, has this shape.
SOZOPOL, ST_IVAN, NESSEBAR = (42.4195, 27.6955), (42.4400, 27.6790), (42.6539, 27.7242)


def leg(dep_lo, dep_hi, arr_lo, arr_hi, a, b, src="nfl"):
    d = "2026-11-02T"
    return tp.Leg(ts(d + dep_lo), ts(d + dep_hi), ts(d + arr_lo), ts(d + arr_hi), a, b, src)


JOURNEY = [leg("00:00", "10:00", "00:10", "10:10", SOZOPOL, ST_IVAN),
           leg("10:20", "18:00", "12:50", "20:00", ST_IVAN, NESSEBAR)]


def test_a_journey_leg_is_retimed_by_the_phone_where_the_phone_had_it():
    phone = [leg("08:48", "08:48", "09:15", "09:15", SOZOPOL, ST_IVAN, "phone"),
             leg("10:00", "23:00", "13:00", "23:59", ST_IVAN, NESSEBAR, "phone")]
    got = tp.retime(JOURNEY, phone)
    assert [g.src for g in got] == ["phone", "nfl"]
    assert got[0].dep_lo == ts("2026-11-02T08:48")


def test_retiming_neither_adds_nor_drops_a_leg():
    # a dinghy-length phone move, and a phone leg somewhere else altogether
    phone = [leg("11:00", "11:00", "11:20", "11:20", ST_IVAN, (42.45, 27.70), "phone")]
    assert tp.retime(JOURNEY, phone) == JOURNEY
    assert tp.retime([], phone) == []


def test_a_vaguer_phone_leg_does_not_retime_a_journey_leg():
    journey = [leg("08:40", "08:50", "09:10", "09:20", SOZOPOL, ST_IVAN)]
    phone = [leg("06:00", "12:00", "07:00", "13:00", SOZOPOL, ST_IVAN, "phone")]
    assert tp.retime(journey, phone) == journey


def test_the_same_place_on_another_day_is_not_the_same_move():
    phone = [leg("08:48", "08:48", "09:15", "09:15", SOZOPOL, ST_IVAN, "phone")]
    phone[0].dep_lo -= 86400 * 2
    phone[0].dep_hi -= 86400 * 2
    phone[0].arr_lo -= 86400 * 2
    phone[0].arr_hi -= 86400 * 2
    assert tp.retime(JOURNEY, phone) == JOURNEY


# The owner's verdicts on spots the generator took for stops, 2026-11-08: open water is
# slow sailing, and a spot on land is the phone carried ashore without the boat.
A, MID, B = (38.30, 23.90), (38.33, 23.95), (38.37, 23.99)


def walk(t0, t1, a, b, src="phone", step=60):
    """Points every `step` seconds from a to b."""
    s, e = ts(t0), ts(t1)
    n = max(1, int((e - s) // step))
    return [tp.Pt(s + (e - s) * k / n, a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n,
                  src, s + (e - s) * k / n, s + (e - s) * k / n) for k in range(n + 1)]


def slow_passage():
    """A to B with a long crawl in the middle: a stop by the numbers, sailing in fact."""
    d = "2024-11-08T"
    return (walk(d + "06:00", d + "07:00", A, A, "nfl", 300)
            + walk(d + "07:00", d + "09:00", A, MID, "nfl", 300)
            + walk(d + "09:00", d + "09:25", MID, MID, "nfl", 300)
            + walk(d + "09:25", d + "12:00", MID, B, "nfl", 300)
            + walk(d + "12:00", d + "13:00", B, B, "nfl", 300))


def test_a_stop_at_a_spot_the_owner_called_open_water_is_sailing():
    d0, d1 = tp.day_window("2024-11-08", "Europe/Athens")
    assert len(tp.passages(slow_passage(), d0, d1, 9e12)) == 2
    legs = tp.passages(slow_passage(), d0, d1, 9e12, at_sea=[MID])
    assert len(legs) == 1
    assert tp.hav(legs[0].a, A) < 300 and tp.hav(legs[0].b, B) < 300


def test_at_sea_and_ashore_entries_are_not_places(tmp_path):
    p = tmp_path / "PLACES.md"
    p.write_text("| Place | Latitude | Longitude |\n|---|---|---|\n"
                 "| Chaika | 43.248 | 28.030 |\n| at sea | 38.33 | 23.95 |\n"
                 "| ashore (not the boat) | 45.0 | 30.0 |\n")
    places, at_sea, ashore = tp.read_places(str(p))
    assert [n for n, _, _ in places] == ["Chaika"]
    assert at_sea == [(38.33, 23.95)]
    assert ashore == [(45.0, 30.0)]


def test_points_at_an_ashore_spot_are_dropped():
    pts = [pt("2026-07-21T16:30", 45.0001, 30.0001, "phone"), pt("2026-07-21T17:00", 45.04, 30.0, "phone")]
    assert tp.not_ashore(pts, [(45.0, 30.0)]) == pts[1:]


def test_a_passage_cut_at_the_window_edge_ends_at_sea_not_at_xxx(tmp_path, monkeypatch):
    places = tmp_path / "PLACES.md"
    places.write_text(f"| at sea | {MID[0]} | {MID[1]} |\n")
    monkeypatch.setattr(tp, "photo_points", lambda photos: [])
    d = "2024-11-08T"
    pts = (walk(d + "06:00", d + "07:00", A, A, "nfl", 300) + walk(d + "07:00", d + "09:00", A, MID, "nfl", 300)
           + walk(d + "09:00", d + "10:00", MID, MID, "nfl", 300))

    class J:
        anchored: set = set()

        def points(self, anchors):
            return pts

        def near(self, lat, lon):
            return True

        def fixes(self):
            return [(*A, ts(d + "06:00")), (*MID, ts(d + "09:00"))]
    sections, _ = tp.generate("## Friday 2024-11-08 - A - B\n", "2024-11-08", "2024-11-08", journey=J(),
                              phone_paths=[], photos="", places_path=str(places))
    assert sections["2024-11-08"][1][-1].endswith("(at sea)")


def test_a_long_stay_on_open_water_stays_a_stop():
    # Kalem/Garip sound, 2025-08-17 .. 20: the owner's "at sea", but the boat lay there for
    # days, and folding that makes a three-day passage
    d = "2024-11-08T"
    pts = (walk(d + "06:00", d + "07:00", A, A, "nfl", 300) + walk(d + "07:00", d + "09:00", A, MID, "nfl", 300)
           + walk(d + "09:00", d + "12:00", MID, MID, "nfl", 300) + walk(d + "12:00", d + "14:00", MID, B, "nfl", 300)
           + walk(d + "14:00", d + "15:00", B, B, "nfl", 300))
    d0, d1 = tp.day_window("2024-11-08", "Europe/Athens")
    assert len(tp.passages(pts, d0, d1, 9e12, at_sea=[MID])) == 2


def journey_line(t0, t1, a, b):
    """Fix at `a` at t0, then vertices towards `b` interpolated up to the next fix at t1."""
    pts = walk(t0, t1, a, b, "nfl", 1800)
    lo, hi = pts[0].t, pts[-1].t
    return [pts[0]._replace(stop=True)] + [p._replace(lo=lo, hi=hi) for p in pts[1:-1]]


def test_an_unmeasured_stay_of_days_on_open_water_stays_a_stop():
    d = "2024-11-"
    pts = (journey_line(d + "08T06:00", d + "08T09:00", A, MID)
           + journey_line(d + "08T09:00", d + "11T09:00", MID, MID)
           + journey_line(d + "11T09:00", d + "11T12:00", MID, B)
           + [tp.Pt(ts(d + "11T12:00"), *B, "nfl", ts(d + "11T12:00"), ts(d + "11T12:00"), True)])
    d0, d1 = tp.day_window("2024-11-08", "Europe/Athens")
    legs = tp.passages(pts, d0, d1, 9e12, at_sea=[MID])
    assert len(legs) == 1 and tp.hav(legs[0].b, MID) < 400


# Stops are anchored on the journey's fixes: the owner's consolidated record of where the
# boat lay, derived from all the sources. A phone carried ashore stops where no fix is.
LAND = (38.335, 23.955)  # a walk ashore, 600 m off the line


def day_with_walk():
    d = "2024-11-08T"
    return (walk(d + "06:00", d + "07:00", A, A, "phone", 120) + walk(d + "07:00", d + "09:00", A, MID, "phone", 120)
            + walk(d + "09:00", d + "09:05", MID, LAND, "phone", 60) + walk(d + "09:05", d + "10:30", LAND, LAND, "phone", 120)
            + walk(d + "10:30", d + "10:35", LAND, MID, "phone", 60) + walk(d + "10:35", d + "12:00", MID, B, "phone", 120)
            + walk(d + "12:00", d + "13:00", B, B, "phone", 120))


def test_a_stop_with_no_journey_fix_near_it_is_no_stop():
    d0, d1 = tp.day_window("2024-11-08", "Europe/Athens")
    fixes = [(*A, ts("2024-11-07T18:00")), (*B, ts("2024-11-08T12:00"))]
    assert len(tp.passages(day_with_walk(), d0, d1, 9e12)) == 2
    legs = tp.passages(day_with_walk(), d0, d1, 9e12, fixes=fixes)
    assert len(legs) == 1


def test_a_leg_reports_the_fix_position():
    d0, d1 = tp.day_window("2024-11-08", "Europe/Athens")
    a_fix, b_fix = (A[0] + 0.001, A[1]), (B[0] - 0.001, B[1])
    fixes = [(*a_fix, ts("2024-11-07T18:00")), (*b_fix, ts("2024-11-08T12:00"))]
    legs = tp.passages(day_with_walk(), d0, d1, 9e12, fixes=fixes)
    assert legs[0].a == a_fix and legs[0].b == b_fix


def test_a_fix_at_the_same_spot_in_another_year_does_not_anchor():
    d0, d1 = tp.day_window("2024-11-08", "Europe/Athens")
    fixes = [(*A, ts("2024-11-07T18:00")), (*LAND, ts("2023-06-01T12:00")), (*B, ts("2024-11-08T12:00"))]
    assert len(tp.passages(day_with_walk(), d0, d1, 9e12, fixes=fixes)) == 1


def test_folding_a_stop_keeps_the_last_stretch_in_the_arrival():
    # the arrival window must not open when the boat left the folded stop: it still had
    # the stretch from there to sail
    d = "2024-11-08T"
    pts = (journey_line(d + "06:00", d + "09:00", A, MID) + journey_line(d + "09:00", d + "12:00", MID, B)
           + [tp.Pt(ts(d + "12:00"), *B, "nfl", ts(d + "12:00"), ts(d + "12:00"), True)])
    d0, d1 = tp.day_window("2024-11-08", "Europe/Athens")
    legs = tp.passages(pts, d0, d1, 9e12, at_sea=[MID])
    assert len(legs) == 1
    assert legs[0].arr_lo >= ts(d + "09:00") + tp.hav(MID, B) / tp.NM / tp.MAX_KTS * 3600 - 60


def test_a_long_stay_is_anchored_by_its_arrival_fix_weeks_before():
    d0, d1 = tp.day_window("2024-11-08", "Europe/Athens")
    fixes = [(*A, ts("2024-10-01T18:00")), (*B, ts("2024-11-08T12:00"))]
    assert len(tp.passages(day_with_walk(), d0, d1, 9e12, fixes=fixes)) == 1


def test_only_the_latest_earlier_fix_anchors_a_long_stay():
    # a fix at A weeks ago, then the boat went elsewhere: the fix no longer says it lies at A
    d0, d1 = tp.day_window("2024-11-08", "Europe/Athens")
    fixes = [(*A, ts("2024-10-01T18:00")), (40.0, 26.0, ts("2024-10-20T12:00")), (*B, ts("2024-11-08T12:00"))]
    assert len(tp.passages(day_with_walk(), d0, d1, 9e12, fixes=fixes)) == 0


# 2025-03-07: the phone was off for two days and on again at sea; it still recorded the
# arrival at the day's last anchorage to the minute. Each end of a journey leg takes the
# phone's time where the phone saw the boat arrive or leave there.
def phone_evening():
    d = "2024-11-08T"
    return (walk(d + "14:44", d + "16:35", MID, MID) + walk(d + "16:35", d + "21:04", MID, B)
            + walk(d + "21:04", d + "23:00", B, B))


def test_a_journey_leg_end_takes_the_phone_arrival_there():
    vague = [leg_at("2024-11-08T00:00", "2024-11-08T12:55", "2024-11-08T13:30", "2024-11-08T23:30", A, B)]
    got = tp.retime_ends(vague, phone_evening())
    # exact, at the moment the track enters the stop's 300 m radius on the slow approach
    assert got[0].arr_lo == got[0].arr_hi
    assert 0 <= ts("2024-11-08T21:04") - got[0].arr_lo <= 15 * 60
    assert got[0].dep_lo == vague[0].dep_lo  # the phone never saw the departure from A


def test_the_phone_switching_on_is_no_arrival():
    vague = [leg_at("2024-11-08T00:00", "2024-11-08T12:55", "2024-11-08T13:30", "2024-11-08T23:30", A, MID)]
    got = tp.retime_ends(vague, phone_evening())
    assert got[0].arr_hi == vague[0].arr_hi


def leg_at(dep_lo, dep_hi, arr_lo, arr_hi, a, b):
    return tp.Leg(ts(dep_lo), ts(dep_hi), ts(arr_lo), ts(arr_hi), a, b, "nfl", tp.hav(a, b), 3600, 36000)


def test_a_phone_departure_moves_the_arrival_window_after_it():
    d = "2024-11-08T"
    phone = walk(d + "10:00", d + "12:54", A, A) + walk(d + "12:54", d + "13:30", A, MID)
    vague = [leg_at(d + "00:00", d + "18:00", d + "01:00", d + "23:00", A, B)]
    got = tp.retime_ends(vague, phone)[0]
    assert got.dep_lo == got.dep_hi >= ts(d + "12:54") - 15 * 60
    assert got.arr_lo >= got.dep_hi + tp.hav(A, B) / tp.NM / tp.MAX_KTS * 3600 - 1


def test_a_leg_reports_at_least_the_line_as_sailed():
    d0, d1 = tp.day_window("2024-11-08", "Europe/Athens")
    a_fix, b_fix = (A[0] - 0.003, A[1]), (B[0] + 0.003, B[1])  # each ~330 m beyond the stop
    fixes = [(*a_fix, ts("2024-11-07T18:00")), (*b_fix, ts("2024-11-08T12:00"))]
    d = "2024-11-08T"
    straight = (walk(d + "06:00", d + "07:00", A, A) + walk(d + "07:00", d + "09:00", A, B)
                + walk(d + "09:00", d + "10:00", B, B))
    leg = tp.passages(straight, d0, d1, 9e12, fixes=fixes)[0]
    assert leg.dist >= leg.line


def test_a_rerun_names_the_generated_sections_it_drops_without_replacing():
    # 2025-07-28's passage moved to the day before: its old section must go, and say so
    assert tp.dropped_days(DIARY, {}, "2026-11-01", "2026-11-30") == ["2026-11-02", "2026-11-03"]
    assert tp.dropped_days(DIARY, {"2026-11-02": (["nfl"], ["* x"])}, "2026-11-01", "2026-11-30") == ["2026-11-03"]


def test_two_stops_anchored_on_one_fix_are_one_stop():
    # the boat shifted 945 m inside one anchorage; both stops lie within 500 m of its fix
    d = "2024-11-08T"
    a2 = (A[0] + 0.0085, A[1])  # 945 m north of A: too far apart to merge as one stop
    mid = ((A[0] + a2[0]) / 2, A[1])
    pts = (walk(d + "05:00", d + "06:00", A, A, "nfl") + walk(d + "06:00", d + "06:10", A, a2, "nfl")
           + walk(d + "06:10", d + "07:00", a2, a2, "nfl") + walk(d + "07:00", d + "09:00", a2, B, "nfl")
           + walk(d + "09:00", d + "10:00", B, B, "nfl"))
    fixes = [(*mid, ts("2024-11-07T18:00")), (*B, ts(d + "09:00"))]
    d0, d1 = tp.day_window("2024-11-08", "Europe/Athens")
    legs = tp.passages(pts, d0, d1, 9e12, fixes=fixes)
    assert len(legs) == 1 and legs[0].a == mid


def test_a_phone_stop_after_the_phone_was_off_is_no_arrival():
    # the phone was off on the way and switched on at the anchorage: no arrival time
    d = "2024-11-08T"
    phone = walk(d + "06:00", d + "07:00", A, A) + walk(d + "07:00", d + "07:10", A, MID) \
        + walk(d + "10:00", d + "11:00", B, B)
    vague = [leg_at(d + "06:00", d + "09:00", d + "08:00", d + "12:00", A, B)]
    got = tp.retime_ends(vague, phone)
    assert got[0].arr_lo == vague[0].arr_lo and got[0].arr_hi == vague[0].arr_hi


def test_unheaded_skips_a_line_with_no_times(tmp_path):
    snap = {"geojson": {"features": [
        {"geometry": {"type": "LineString", "coordinates": [[23.9, 38.3], [24.5, 38.5]]},
         "properties": {"fixId": 1}},
        {"geometry": {"type": "Point", "coordinates": [24.5, 38.5]},
         "properties": {"fixId": 1, "timeMs": 1731067200000, "source": "Manual"}}]}}
    p = tmp_path / "snap.json"
    p.write_text(json.dumps(snap))
    assert tp.Journey(str(p)).unheaded("", "2024-01-01", "2024-12-31") == []
