"""Shift a polyline sideways from its own course.

The 2021 return legs have no track of their own. What exists is the *inbound* track for
the same water, already hand-routed on the map by the owner to keep it off the land, so
the honest way to draw the return is to reverse it. That leaves two lines sharing every
vertex: they render as one, and nothing on the map says which direction belongs to which
date.

Moving the outbound line a boat's width to starboard fixes both, and is what happened
anyway - you keep to your own side of a channel. The owner set the specification:

    "let the inbound track be ~15 meters on the port side of me when doing the
     outbound track"

Port is left of the direction of travel, so the line being drawn moves to **starboard**
of its own course. `metres` is positive for starboard, negative for port.

This is a small-offset approximation, deliberately: 15 m at Bohuslän latitudes, where a
flat-earth step in latitude and cos-scaled longitude is accurate to well under a
millimetre. It is not for offsetting by miles.
"""
import math

from boattracker.nfl.leg_export import hav  # one copy of the distance function, not a fourth

R = 6371000.0

__all__ = ['hav', 'offset_polyline']


def _headings(points):
    """Unit course vector at each vertex, in (east, north) components.

    A vertex between two segments takes the **average** of their directions rather than
    either one, so a bend offsets along the bisector and the offset line keeps its
    corner instead of kinking across itself. Zero-length segments - which the rendered
    geometry produces constantly, because every noforeignland line repeats the previous
    fix's position as its first vertex - carry no direction and inherit a neighbour's.
    """
    segs = []
    for (la1, lo1), (la2, lo2) in zip(points, points[1:]):
        de = (lo2 - lo1) * math.cos(math.radians((la1 + la2) / 2))
        dn = la2 - la1
        n = math.hypot(de, dn)
        segs.append(None if n == 0 else (de / n, dn / n))

    def fill(i, step):
        while 0 <= i < len(segs):
            if segs[i] is not None:
                return segs[i]
            i += step
        return None

    for i in range(len(segs)):                      # a zero segment borrows a real one
        if segs[i] is None:
            segs[i] = fill(i, 1) or fill(i, -1) or (0.0, 1.0)

    out = []
    for i in range(len(points)):
        a = segs[i - 1] if i > 0 else segs[0]
        b = segs[i] if i < len(segs) else segs[-1]
        de, dn = a[0] + b[0], a[1] + b[1]
        n = math.hypot(de, dn)
        out.append(b if n == 0 else (de / n, dn / n))   # a hairpin keeps the outgoing leg
    return out


def offset_polyline(points, metres):
    """[(lat, lon)] shifted `metres` to starboard of its own direction of travel.

    Negative `metres` shifts to port. Lines of fewer than two points, and an offset of
    zero, come back untouched.
    """
    if len(points) < 2 or metres == 0:
        return list(points)
    deg = 180 / (math.pi * R)                        # metres -> degrees of latitude
    out = []
    for (lat, lon), (de, dn) in zip(points, _headings(points)):
        # starboard is the course turned 90 deg clockwise: (east, north) -> (north, -east)
        se, sn = dn, -de
        dlat = metres * sn * deg
        dlon = metres * se * deg / math.cos(math.radians(lat))
        out.append((lat + dlat, lon + dlon))
    return out
