"""Tests for omaps_export.py — the Organic Maps KMZ/KML reader."""
import os
import zipfile

import pytest

from boattracker.nfl.omaps_export import Fix, load, tracks

KML = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2" xmlns:gx="http://www.google.com/kml/ext/2.2">
<Document>
  <Placemark>
    <name>Bollard</name>
    <Point><coordinates>9.67227,45.687059,0</coordinates></Point>
  </Placemark>
  <Placemark>
    <name>August 14, 2026 at 5:57 PM</name>
    <gx:MultiTrack>
      <gx:Track>
        <when>2026-08-07T09:00:00Z</when>
        <when>2026-08-07T10:00:00Z</when>
        <when>2045-08-02T15:35:04Z</when>
        <gx:coord>28.7055 43.5545 0</gx:coord>
        <gx:coord>28.6675 43.9219 0</gx:coord>
        <gx:coord>28.6621 44.1768 0</gx:coord>
      </gx:Track>
    </gx:MultiTrack>
  </Placemark>
</Document>
</kml>
"""


@pytest.fixture
def kml_path(tmp_path):
    p = tmp_path / "My Places.kml"
    p.write_text(KML)
    return str(p)


@pytest.fixture
def kmz_path(tmp_path, kml_path):
    p = tmp_path / "My Places.kmz"
    with zipfile.ZipFile(p, "w") as z:
        z.write(kml_path, "My Places.kml")
    return str(p)


def test_tracks_reads_name_and_points(kml_path):
    trks = tracks(kml_path)
    assert len(trks) == 1
    assert trks[0].name == "August 14, 2026 at 5:57 PM"
    assert len(trks[0].fixes) == 3


def test_when_and_coord_are_paired_by_index(kml_path):
    """`<when>` is in the KML namespace and `<gx:coord>` in gx — a reader that
    looks for `gx:when` silently returns zero timestamps for every track. And the
    two are written as two consecutive blocks, not interleaved, so they pair by
    index; pairing each `<when>` with the *following* coord yields one fix."""
    fixes = tracks(kml_path)[0].fixes
    assert (round(fixes[0].lat, 4), round(fixes[0].lon, 4)) == (43.5545, 28.7055)
    assert fixes[0].t.year == 2026 and fixes[0].t.day == 7
    assert (round(fixes[2].lat, 4), round(fixes[2].lon, 4)) == (44.1768, 28.6621)


def test_a_truncated_track_keeps_the_aligned_prefix(tmp_path):
    p = tmp_path / "cut.kml"
    p.write_text(KML.replace("        <gx:coord>28.6621 44.1768 0</gx:coord>\n", ""))
    fixes = tracks(str(p))[0].fixes
    assert len(fixes) == 2
    assert (round(fixes[1].lat, 4), round(fixes[1].lon, 4)) == (43.9219, 28.6675)


def test_kmz_is_read_like_kml(kmz_path, kml_path):
    assert [f.t for f in load(kmz_path)] == [f.t for f in load(kml_path)]


def test_load_flattens_sorted_and_drops_implausible_years(kml_path):
    """The real export carries a 2045 timestamp; a fix dated after the export
    itself is a phone clock glitch and must not become dating evidence."""
    fixes = load(kml_path, max_year=2026)
    assert len(fixes) == 2
    assert [f.t for f in fixes] == sorted(f.t for f in fixes)


def test_load_keeps_out_of_range_fixes_when_not_filtering(kml_path):
    assert len(load(kml_path, max_year=None)) == 3


def test_placemarks_without_a_track_are_ignored(kml_path):
    assert all(t.name != "Bollard" for t in tracks(kml_path))


def test_fix_is_comparable_by_time():
    a = Fix(1.0, 2.0, __import__("datetime").datetime(2026, 1, 1))
    b = Fix(1.0, 2.0, __import__("datetime").datetime(2026, 1, 2))
    assert min(a, b) is a


def test_real_export_if_present():
    p = os.path.expanduser("~/Downloads/newmi/My Places (2).kmz")
    if not os.path.exists(p):
        pytest.skip("phone export not on this machine")
    fixes = load(p)
    assert len(fixes) > 100000
    assert fixes[0].t < fixes[-1].t
