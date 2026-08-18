"""Tests for the manual-location overlay.

The overlay carries the owner's recall, and the rule that makes it trustworthy is that
recall never quietly displaces measurement. But a camera can write a position that is
simply false — a cached lock 900 nm away — and that case has to be correctable, or the
index holds a fiction nothing can override. Hence `override` and `drop`: both explicit,
both leaving the original visible in the merged record.
"""

import json

from boattracker.nfl import exif_index


def merge(records, entries, tmp_path):
    p = tmp_path / "manual.json"
    p.write_text(json.dumps(entries), encoding="utf-8")
    have = {r["path"]: r for r in records}
    return exif_index.apply_manual(have, str(p))


def rec(path="a.jpg", time="2022-07-23T21:57:46", lat=None, lon=None):
    return {"path": path, "time": time, "lat": lat, "lon": lon, "model": "CLT-L29"}


def test_recall_fills_a_missing_position(tmp_path):
    out = merge([rec(lat=None)], [{"path": "a.jpg", "lat": 53.89, "lon": 9.14, "ashore": False}], tmp_path)
    assert out["a.jpg"]["lat"] == 53.89
    assert out["a.jpg"]["position_from"] == "recalled"


def test_recall_does_not_silently_displace_a_measured_position(tmp_path):
    out = merge([rec(lat=54.3633, lon=18.6578)],
                [{"path": "a.jpg", "lat": 53.89, "lon": 9.14, "ashore": False}], tmp_path)
    assert out["a.jpg"]["lat"] == 54.3633, "an entry without override must not overwrite EXIF"


def test_override_replaces_a_false_position_and_keeps_the_original(tmp_path):
    out = merge([rec(lat=54.3633, lon=18.6578)],
                [{"path": "a.jpg", "lat": 53.89, "lon": 9.14, "ashore": False, "override": True,
                  "note": "EXIF says Gdansk; the picture is a Kiel canal lock"}], tmp_path)
    r = out["a.jpg"]
    assert (r["lat"], r["lon"]) == (53.89, 9.14)
    assert r["position_from"] == "corrected"
    assert (r["exif_lat"], r["exif_lon"]) == (54.3633, 18.6578), "the original must stay auditable"


def test_drop_discards_a_false_position_without_inventing_one(tmp_path):
    out = merge([rec(lat=54.3633, lon=18.6578)],
                [{"path": "a.jpg", "drop": True, "note": "false fix, true place unknown"}], tmp_path)
    r = out["a.jpg"]
    assert r["lat"] is None and r["lon"] is None
    assert r["position_from"] == "dropped"
    assert (r["exif_lat"], r["exif_lon"]) == (54.3633, 18.6578)


def test_override_by_day_applies_to_every_photograph_of_that_day(tmp_path):
    rows = [rec(path="a.jpg", time="2022-07-23T13:50:00", lat=54.3633, lon=18.6578),
            rec(path="b.jpg", time="2022-07-23T21:57:00", lat=54.3633, lon=18.6578)]
    out = merge(rows, [{"day": "2022-07-23", "lat": 53.89, "lon": 9.14,
                        "ashore": False, "override": True}], tmp_path)
    assert all(out[p]["lat"] == 53.89 for p in ("a.jpg", "b.jpg"))
    assert all(out[p]["position_from"] == "corrected" for p in ("a.jpg", "b.jpg"))


def test_an_ashore_entry_does_not_move_a_true_position(tmp_path):
    """The 2021-05-16 case: photographs really were in Goteborg, the boat lay at Stromstad.

    The entry carries the boat's position as context, but the photograph is not wrong and
    must stay where it was taken. Only `ashore` applies — this is why `override` exists as
    a separate key rather than being implied by supplying coordinates.
    """
    rows = [rec(path="a.jpg", time="2021-05-16T10:00:00", lat=57.70, lon=11.97)]
    out = merge(rows, [{"day": "2021-05-16", "lat": 58.929787, "lon": 11.170643,
                        "ashore": True}], tmp_path)
    assert (out["a.jpg"]["lat"], out["a.jpg"]["lon"]) == (57.70, 11.97)
    assert out["a.jpg"]["ashore"] is True
    assert "position_from" not in out["a.jpg"]


def test_a_path_entry_wins_over_a_day_entry(tmp_path):
    rows = [rec(path="a.jpg", time="2022-07-23T10:00:00", lat=54.36, lon=18.65)]
    out = merge(rows, [{"day": "2022-07-23", "lat": 53.89, "lon": 9.14, "ashore": False, "override": True},
                       {"path": "a.jpg", "lat": 53.90, "lon": 9.15, "ashore": False, "override": True}],
                tmp_path)
    assert out["a.jpg"]["lat"] == 53.90


def test_a_path_entry_marks_only_that_photograph(tmp_path):
    """The 2021-05-17 case: two morning photographs ashore in Stromstad, and from 15:45 the
    boat is under way south. A day-level flag there would discard the whole passage to
    Hamburgsund, so the entries are path-keyed and must not leak to the rest of the day.
    """
    rows = [rec(path="huawei/IMG_20210517_093059.jpg", time="2021-05-17T09:30:59", lat=58.9298, lon=11.1706),
            rec(path="huawei/IMG_20210517_154500.jpg", time="2021-05-17T15:45:00", lat=58.85, lon=11.15)]
    out = merge(rows, [{"path": "huawei/IMG_20210517_093059.jpg", "lat": 58.929787,
                        "lon": 11.170643, "ashore": True}], tmp_path)
    assert out["huawei/IMG_20210517_093059.jpg"]["ashore"] is True
    assert out["huawei/IMG_20210517_154500.jpg"].get("ashore") is None
    assert out["huawei/IMG_20210517_154500.jpg"]["lat"] == 58.85


def test_ashore_flag_still_rides_along_without_any_position(tmp_path):
    out = merge([rec(lat=69.66, lon=18.95)], [{"day": "2022-07-23", "ashore": True}], tmp_path)
    assert out["a.jpg"]["lat"] == 69.66, "no position given, so nothing to replace"
    assert out["a.jpg"]["ashore"] is True
