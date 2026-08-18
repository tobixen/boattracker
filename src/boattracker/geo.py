"""The one haversine, in the two units this project measures in.

Sixteen copies of it existed here on 2026-08-17, differing only in whether they returned
metres or nautical miles and whether they sliced `a[:2]` before unpacking. Five were in
tools that still run and are now aliases of this module; the eleven in the frozen session
scripts are left where they are, because those files are the record of a past run rather
than code expected to execute again.

**This is not the solver `point.py` uses.** The parser measures with
`geopy.distance.distance`, i.e. Karney's ellipsoid geodesic, and every distance recorded in
the archive by the parser was computed that way - see TODO.md, "Why `test_parser.py` is
slow", for the measured 16x cost of that choice and the reason it has not been changed. The
two differ by well under a metre at the scales the gap scans work at, but they are
different numbers and a figure should say which one produced it.
"""

import math

R_EARTH = 6371000.0  ## mean radius in metres - the value all sixteen copies used
NM = 1852.0


def hav(a: tuple, b: tuple) -> float:
    """Great-circle distance in metres between two (lat, lon) points, in degrees.

    Elements past the second are ignored, so a journey vertex `(lat, lon, epoch)` or a
    plotter point carrying its own metadata can be passed straight in.
    """
    (la1, lo1), (la2, lo2) = a[:2], b[:2]
    p = math.pi / 180
    h = (math.sin((la2 - la1) * p / 2) ** 2
         + math.cos(la1 * p) * math.cos(la2 * p) * math.sin((lo2 - lo1) * p / 2) ** 2)
    return 2 * R_EARTH * math.asin(math.sqrt(h))


def hav_nm(a: tuple, b: tuple) -> float:
    """The same distance in nautical miles, which is what the gap and backtrack scans report."""
    return hav(a, b) / NM
