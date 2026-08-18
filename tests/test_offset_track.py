"""Tests for offsetting a polyline sideways from its own course.

Why this exists: the 2021 return legs are built by reversing the *inbound* track, which
means the outbound line would be drawn exactly on top of the inbound one. Two tracks
sharing every vertex render as one, and worse, a later reader cannot tell which is
which. Shifting the outbound line a boat's width to starboard separates them and is
also what actually happened - you keep to your own side.

The owner's phrasing is the specification: "let the inbound track be ~15 meters on the
port side of me when doing the outbound track". Port is left of the direction of travel,
so the outbound line moves to *starboard* of the course it is being drawn along.
"""

import math

from boattracker.nfl import offset_track as o


def test_a_northbound_leg_moves_east():
    """Heading 000, starboard is 090. The offset must go east, not west.

    Getting this backwards is invisible on a map at any sensible zoom - both lines look
    parallel and 15 m apart - and would put the boat on the wrong side of the channel.
    """
    out = o.offset_polyline([(58.0, 11.0), (58.1, 11.0)], 15.0)
    assert all(lon > 11.0 for _, lon in out), out
    assert all(abs(lat - want) < 1e-6 for (lat, _), want in zip(out, (58.0, 58.1)))


def test_a_southbound_leg_moves_west():
    out = o.offset_polyline([(58.1, 11.0), (58.0, 11.0)], 15.0)
    assert all(lon < 11.0 for _, lon in out), out


def test_an_eastbound_leg_moves_south():
    out = o.offset_polyline([(58.0, 11.0), (58.0, 11.2)], 15.0)
    assert all(lat < 58.0 for lat, _ in out), out


def test_the_offset_distance_is_what_was_asked_for():
    a, b = (58.0, 11.0), (58.1, 11.0)
    out = o.offset_polyline([a, b], 15.0)
    for src, dst in zip((a, b), out):
        assert abs(o.hav(src, dst) - 15.0) < 0.5, (src, dst, o.hav(src, dst))


def test_longitude_is_scaled_by_latitude():
    """15 m of easting is a bigger longitude step at 58 N than at the equator.

    Forgetting the cos(lat) factor is the classic error here and would put the line
    ~28 m out at Bohuslän latitudes - nearly twice the requested offset.
    """
    north = o.offset_polyline([(58.0, 11.0), (58.1, 11.0)], 15.0)
    equator = o.offset_polyline([(0.0, 11.0), (0.1, 11.0)], 15.0)
    assert (north[0][1] - 11.0) > 1.8 * (equator[0][1] - 11.0)


def test_a_corner_offsets_along_the_bisector_not_past_it():
    """At a bend the two adjacent segments disagree about which way is starboard.

    Using either one alone kinks the offset line and can cross it over itself on a
    tight turn. The vertex takes the average heading, so the offset corner stays a
    corner and stays on the correct side of both segments.
    """
    pts = [(58.0, 11.0), (58.1, 11.0), (58.1, 11.2)]   # north, then east
    out = o.offset_polyline(pts, 15.0)
    assert len(out) == 3
    assert out[1][0] < 58.1 and out[1][1] > 11.0       # inside the corner: SE of it
    for src, dst in zip(pts, out):
        assert 10.0 < o.hav(src, dst) < 22.0


def test_duplicate_consecutive_points_do_not_divide_by_zero():
    """The rendered geometry really does repeat its first vertex.

    Every noforeignland line begins with the previous fix's position, so a duplicated
    point is the normal case, not a defect. A zero-length segment has no heading and
    must inherit its neighbour's rather than blow up.
    """
    out = o.offset_polyline([(58.0, 11.0), (58.0, 11.0), (58.1, 11.0)], 15.0)
    assert len(out) == 3
    assert all(not math.isnan(v) for p in out for v in p)
    assert all(lon > 11.0 for _, lon in out)


def test_a_single_point_and_an_empty_line_are_returned_untouched():
    assert o.offset_polyline([], 15.0) == []
    assert o.offset_polyline([(58.0, 11.0)], 15.0) == [(58.0, 11.0)]


def test_offsetting_by_zero_changes_nothing():
    pts = [(58.0, 11.0), (58.1, 11.05)]
    assert o.offset_polyline(pts, 0.0) == pts


def test_port_is_the_mirror_of_starboard():
    pts = [(58.0, 11.0), (58.1, 11.0)]
    stbd = o.offset_polyline(pts, 15.0)
    port = o.offset_polyline(pts, -15.0)
    for (la1, lo1), (la2, lo2) in zip(stbd, port):
        assert abs((lo1 - 11.0) + (lo2 - 11.0)) < 1e-9
        assert abs(la1 - la2) < 1e-9
