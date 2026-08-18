"""Tests for timestamp_segments.py — dating plotter geometry from phone fixes."""
from datetime import UTC, datetime, timedelta

import pytest

from boattracker.nfl.omaps_export import Fix
from boattracker.nfl.timestamp_segments import (
    Segment,
    drop_off_planet,
    interpolate,
    load_segments,
    match,
)

GPX = """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="Raymarine" xmlns="http://www.topografix.com/GPX/1/1"
     xmlns:raymarine="http://www.raymarine.com">
 <trk><name>Track 66</name>
  <extensions><raymarine:TrackExtension>
   <raymarine:GUID>bd80-5323-024c-db01</raymarine:GUID>
  </raymarine:TrackExtension></extensions>
  <trkseg>
   <trkpt lon="28.6621" lat="44.1769"/>
   <trkpt lon="28.6000" lat="44.0000"/>
   <trkpt lon="28.5000" lat="43.8000"/>
  </trkseg>
  <trkseg>
   <trkpt lon="-77.0541" lat="-12.0315"/>
   <trkpt lon="-77.0574" lat="-12.0440"/>
  </trkseg>
 </trk>
 <trk><name>Track 67W</name>
  <trkseg>
   <trkpt lon="28.4525" lat="43.3789"/>
   <trkpt lon="28.3828" lat="43.3542"/>
  </trkseg>
 </trk>
</gpx>
"""

T0 = datetime(2026, 8, 9, 14, 0, tzinfo=UTC)


@pytest.fixture
def gpx(tmp_path):
    p = tmp_path / "Tracks.gpx"
    p.write_text(GPX)
    return str(p)


def test_load_segments_reads_lon_before_lat(gpx):
    """Raymarine writes lon= before lat=; a regex assuming lat first silently
    finds nothing and every segment reads as empty."""
    segs = load_segments(gpx)
    assert [(s.track, s.idx, len(s.points)) for s in segs] == [
        ("Track 66", 0, 3), ("Track 66", 1, 2), ("Track 67W", 0, 2)]
    assert segs[0].points[0] == (44.1769, 28.6621)


def test_load_segments_filters_by_track(gpx):
    assert {s.track for s in load_segments(gpx, tracks=["Track 67W"])} == {"Track 67W"}


def test_segment_length_and_guid(gpx):
    segs = load_segments(gpx)
    assert 20 < segs[0].nm < 30
    assert segs[0].guid == "bd80-5323-024c-db01"


def test_drop_off_planet_removes_the_peru_segments(gpx):
    """The plotter 'decided we were in Peru, cruising in a circle in 109 knots'
    (diary, 2026-08-07): whole segments land at -12.04, -77.05."""
    kept, dropped = drop_off_planet(load_segments(gpx))
    assert [(s.track, s.idx) for s in dropped] == [("Track 66", 1)]
    assert len(kept) == 2


def test_drop_off_planet_keeps_everything_when_nothing_is_far(gpx):
    segs = [s for s in load_segments(gpx) if s.idx == 0]
    kept, dropped = drop_off_planet(segs)
    assert dropped == [] and len(kept) == 2


def phone_line(n=40, start=T0, minutes=6.0):
    """Phone fixes walking the same water as Track 66 s0, one every `minutes`."""
    out = []
    for i in range(n):
        f = i / (n - 1)
        out.append(Fix(44.1769 + f * (43.8000 - 44.1769),
                       28.6621 + f * (28.5000 - 28.6621),
                       start + timedelta(minutes=minutes * i)))
    return out


def test_match_returns_ordered_anchors_and_a_plausible_speed(gpx):
    seg = load_segments(gpx)[0]
    m = match(seg, phone_line(), radius_m=2000)
    assert m is not None
    assert m.tau > 0.9
    assert m.t0 == T0
    assert 0.4 < m.knots < 9.0
    assert [a.i for a in m.anchors] == sorted(a.i for a in m.anchors)


def test_match_rejects_a_shuffled_coincidence(gpx):
    """Same water, wrong visit: the matched times come back out of order, which
    is the only thing that separates a real day from a revisit."""
    fixes = phone_line()
    times = [f.t for f in fixes]
    shuffled = [Fix(f.lat, f.lon, t) for f, t in zip(fixes, reversed(times))]
    m = match(load_segments(gpx)[0], shuffled, radius_m=2000, min_tau=0.5)
    assert m is None


def test_match_returns_none_when_the_phone_was_elsewhere(gpx):
    m = match(load_segments(gpx)[2], phone_line(), radius_m=150)
    assert m is None


def test_interpolate_gives_every_point_a_time_between_the_anchors(gpx):
    seg = load_segments(gpx)[0]
    m = match(seg, phone_line(), radius_m=2000)
    times = interpolate(seg, m)
    assert len(times) == len(seg.points)
    assert times == sorted(times)
    assert times[0] == m.t0 and times[-1] == m.t1


def test_interpolate_spaces_by_distance_not_by_index():
    """Cumulative distance is the clock's proxy, so the midpoint of a leg whose
    first hop is three times the second must not land at the halfway time."""
    seg = Segment("T", 0, [(43.0, 28.0), (43.03, 28.0), (43.04, 28.0)])
    m = match(seg, [Fix(43.0, 28.0, T0),
                    Fix(43.04, 28.0, T0 + timedelta(hours=4))],
              radius_m=200, min_anchors=2)
    times = interpolate(seg, m)
    assert times[1] - times[0] == timedelta(hours=3)
