"""Tests for the fix payload builder.

The payload is form-encoded, not JSON — that is the detail most likely to be
mis-remembered later, so it is pinned here.
"""

from boattracker.nfl import add_fixes


def test_payload_is_form_encoded_with_the_four_observed_fields():
    body = add_fixes.payload(43.18995330534987, 27.920852659309418, 1753221600000)
    assert sorted(f.split("=")[0] for f in body.split("&")) == ["boatId", "lat", "lon", "timestamp"]
    assert f"boatId={add_fixes.BOAT_ID}" in body
    assert "timestamp=1753221600000" in body


def test_payload_keeps_full_coordinate_precision():
    # Truncating here would move a berth fix off the quay.
    body = add_fixes.payload(43.18995330534987, 27.920852659309418, 0)
    assert "lat=43.18995330534987" in body
    assert "lon=27.920852659309418" in body


def test_when_parses_local_time_and_bare_dates():
    # A bare date means local midnight, matching how the web UI writes a backdated fix.
    assert add_fixes.when("2026-03-05") == 1772665200000
    assert add_fixes.when("2026-03-05T00:00") == 1772665200000
    # And an explicit time of day survives, which is the point of doing this by script.
    assert add_fixes.when("2026-03-05T09:30") == 1772699400000


def test_load_plan_accepts_the_four_column_form(tmp_path):
    p = tmp_path / "plan.json"
    p.write_text('[[43.1, 27.9, "2026-03-05", "G G Yacht Club, winter"]]', encoding="utf-8")
    assert add_fixes.load_plan(str(p)) == [(43.1, 27.9, "2026-03-05", "G G Yacht Club, winter")]
