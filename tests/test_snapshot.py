"""Tests for snapshot.py — the line-oriented journey snapshot writer.

The point of the module is that a snapshot committed to git produces a diff a human can
read, so the tests are mostly about *shape*: one vertex per line, deterministic bytes, and
— the property everything else serves — a deleted fix showing up as its own lines going
away and at most one neighbouring line changing its trailing comma.
"""
import difflib
import io
import json

import pytest

from boattracker.nfl.snapshot import dumps

BOAT = 4718293690613760


def fix(fid, ms, lon, lat, line=None):
    """The two features the journey carries per fix: the Point, and the drawn LineString."""
    point = {"type": "Feature",
             "properties": {"id": fid, "source": "GPX Export", "fixId": fid,
                            "layer": "fixes", "timeMs": ms, "boatId": BOAT},
             "geometry": {"type": "Point", "coordinates": [lon, lat, float(ms)]}}
    if line is None:
        return [point]
    return [point, {"type": "Feature",
                    "properties": {"fixId": fid, "boatId": BOAT},
                    "geometry": {"type": "LineString", "coordinates": line}}]


@pytest.fixture
def doc():
    feats = (fix(1, 1620916200000, 10.575933, 59.6655)
             + fix(2, 1620916300000, 10.6, 59.7,
                   line=[[10.575933, 59.6655, 1620916200000.0],
                         [10.58, 59.68, 1620916250000.0],
                         [10.6, 59.7, 1620916300000.0]])
             + fix(3, 1620916400000, 10.7, 59.8))
    return {"geojson": {"features": feats}, "stories": [], "chapters":
            [{"boatId": BOAT, "days": 24, "id": 4279, "miles": 338, "name": "2021-05",
              "start": 1620856800000}],
            "days": 1927, "countries": 19, "status": "ok", "miles": 16529}


def test_round_trips(doc):
    assert json.loads(dumps(doc)) == doc


def test_is_deterministic(doc):
    assert dumps(doc) == dumps(doc)


def test_key_insertion_order_does_not_change_the_bytes(doc):
    shuffled = json.loads(json.dumps(doc))
    props = shuffled["geojson"]["features"][0]["properties"]
    for k in list(props):                      # re-insert in reverse, same content
        props[k] = props.pop(k)
    assert dumps(shuffled) == dumps(doc)


def test_one_line_per_vertex(doc):
    lines = dumps(doc).splitlines()
    vertices = [ln for ln in lines if ln.strip().startswith("[10.5") or ln.strip().startswith("[10.6")]
    # three LineString vertices, each alone on its line
    assert sum(ln.strip().rstrip(",").endswith("]") for ln in vertices) == len(vertices)
    assert len([ln for ln in lines if ln.strip().startswith("[10.58")]) == 1


def test_a_line_is_never_the_whole_file(doc):
    """The failure mode this module exists to prevent: 2.4 MB on one line."""
    assert max(len(ln) for ln in dumps(doc).splitlines()) < 400


def test_deleting_a_fix_is_a_local_diff(doc):
    """Remove the middle fix and its line; nothing else in the file may move."""
    before = dumps(doc).splitlines()
    doc["geojson"]["features"] = [f for f in doc["geojson"]["features"]
                                  if f["properties"].get("fixId") != 2]
    after = dumps(doc).splitlines()
    changed = [ln for ln in difflib.unified_diff(before, after, n=0, lineterm="")
               if ln[:1] in "+-" and ln[:3] not in ("+++", "---")]
    assert all(ln.startswith("-") for ln in changed), "a deletion must not rewrite other lines"
    assert any("1620916300000" in ln for ln in changed)
    assert len(changed) < 15


def test_deleting_the_last_fix_moves_only_the_neighbouring_comma(doc):
    """The newest fix is the last Point, so its neighbour loses a trailing comma. Nothing more."""
    before = dumps(doc).splitlines()
    doc["geojson"]["features"] = doc["geojson"]["features"][:-1]
    after = dumps(doc).splitlines()
    added = [ln[1:] for ln in difflib.unified_diff(before, after, n=0, lineterm="")
             if ln.startswith("+") and not ln.startswith("+++")]
    assert len(added) == 1
    assert added[0] + "," in before


def test_integral_floats_are_written_as_integers(doc):
    """The API sends epoch milliseconds as 1.6209162E12; that is noise in a diff."""
    assert "1620916200000.0" not in dumps(doc)
    assert "1620916200000" in dumps(doc)


def test_integral_floats_outside_coordinates_are_written_as_integers(doc):
    doc["geojson"]["features"][0]["properties"]["timeMs"] = 1.6209162e12
    doc["miles"] = 16529.0
    text = dumps(doc)
    assert "1620916200000.0" not in text and "16529.0" not in text
    assert json.loads(text) == doc


def test_a_null_geometry_round_trips(doc):
    doc["geojson"]["features"].append({"type": "Feature", "properties": {}, "geometry": None})
    assert json.loads(dumps(doc)) == doc


def test_unknown_feature_and_geometry_keys_are_kept_and_reported(doc):
    from boattracker.nfl.snapshot import unknown_keys
    doc["geojson"]["features"][0]["id"] = 17
    doc["geojson"]["features"][1]["geometry"]["bbox"] = [10.5, 59.6, 10.6, 59.7]
    assert json.loads(dumps(doc)) == doc
    found = unknown_keys(doc)
    assert any("'id'" in u for u in found) and any("'bbox'" in u for u in found)


def test_a_known_shape_reports_nothing(doc):
    from boattracker.nfl.snapshot import unknown_keys
    assert unknown_keys(doc) == []


## main(), end to end, from a file rather than the network.

def run(*args):
    from boattracker.nfl.snapshot import main
    return main(list(args))


@pytest.fixture
def src(tmp_path, doc):
    """The API's own spelling: one line, E-notation, non-ASCII story text."""
    p = tmp_path / "reply.json"
    text = json.dumps(doc, separators=(",", ":"), ensure_ascii=False)
    text = text.replace("1620916200000.0", "1.6209162E12").replace('"stories":[]', '"stories":["Ærø"]')
    p.write_bytes(text.encode("utf-8"))
    return p


def test_main_writes_the_line_oriented_snapshot(tmp_path, src):
    out = tmp_path / "snap.json"
    assert run("--from-file", str(src), "--out", str(out)) == 0
    assert json.loads(out.read_text()) == json.loads(src.read_text())
    assert sorted(p.name for p in tmp_path.iterdir()) == ["reply.json", "snap.json"]


def test_main_raw_writes_the_reply_byte_for_byte(tmp_path, src):
    out = tmp_path / "before.json"
    assert run("--from-file", str(src), "--raw", "--out", str(out)) == 0
    assert out.read_bytes() == src.read_bytes()


def test_main_raw_refuses_to_overwrite_an_earlier_copy(tmp_path, src):
    out = tmp_path / "before.json"
    out.write_bytes(b"the morning's copy")
    assert run("--from-file", str(src), "--raw", "--out", str(out)) == 1
    assert out.read_bytes() == b"the morning's copy"


def test_main_refuses_a_nan_coordinate_without_a_traceback(tmp_path, doc):
    doc["geojson"]["features"][0]["geometry"]["coordinates"][0] = float("nan")
    src = tmp_path / "reply.json"
    src.write_text(json.dumps(doc))
    out = tmp_path / "snap.json"
    assert run("--from-file", str(src), "--out", str(out)) == 1
    assert not out.exists()


def test_main_if_changed_leaves_a_drift_only_file_alone(tmp_path, doc):
    src, out = tmp_path / "reply.json", tmp_path / "snap.json"
    src.write_text(json.dumps(doc))
    assert run("--from-file", str(src), "--out", str(out)) == 0
    written = out.read_bytes()
    doc["days"] += 1
    src.write_text(json.dumps(doc))
    assert run("--from-file", str(src), "--out", str(out), "--if-changed") == 0
    assert out.read_bytes() == written


def test_main_warns_about_keys_it_does_not_know(tmp_path, doc, capsys):
    doc["geojson"]["features"][0]["id"] = 17
    src, out = tmp_path / "reply.json", tmp_path / "snap.json"
    src.write_text(json.dumps(doc))
    assert run("--from-file", str(src), "--out", str(out)) == 0
    assert "'id'" in capsys.readouterr().err
    assert json.loads(out.read_text()) == doc


def test_main_survives_a_reply_without_miles(tmp_path, doc):
    doc["miles"] = None
    src, out = tmp_path / "reply.json", tmp_path / "snap.json"
    src.write_text(json.dumps(doc))
    assert run("--from-file", str(src), "--out", str(out)) == 0


def test_dump_writes_the_same_thing_as_dumps(doc):
    from boattracker.nfl.snapshot import dump
    buf = io.StringIO()
    dump(doc, buf)
    assert buf.getvalue() == dumps(doc)


def test_only_drift_sees_through_the_calendar_counters(doc):
    """`days` grew 1927 -> 1949 between two real snapshots with no data change behind it."""
    from boattracker.nfl.snapshot import only_drift
    before = dumps(doc)
    doc["days"] += 22
    doc["chapters"][0]["days"] += 22
    assert only_drift(before, doc)


def test_only_drift_is_false_when_a_fix_goes(doc):
    from boattracker.nfl.snapshot import only_drift
    before = dumps(doc)
    doc["days"] += 22
    doc["geojson"]["features"] = doc["geojson"]["features"][:-1]
    assert not only_drift(before, doc)


def test_only_drift_is_false_on_an_unreadable_file(doc):
    from boattracker.nfl.snapshot import only_drift
    assert not only_drift("not json at all", doc)
