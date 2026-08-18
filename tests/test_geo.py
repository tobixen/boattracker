"""One haversine, and the names the callers already use for it.

Sixteen copies of `def hav` existed on 2026-08-17, byte-identical apart from whether they
returned metres or nautical miles and whether they sliced `a[:2]`. Five of those were in
tools that still run; the rest are in frozen session scripts. These tests pin the shared
one, and - just as importantly - pin the *aliases*, because callers reach it as `LE.hav`,
`FG.hav` and `from leg_export import hav`, and a rename would break them silently.
"""

import math

from boattracker import geo

ONE_DEGREE_OF_LATITUDE = 2 * math.pi * geo.R_EARTH / 360  ## ~111195 m on a sphere


def test_a_degree_of_latitude_is_the_spherical_value():
    assert abs(geo.hav((0.0, 0.0), (1.0, 0.0)) - ONE_DEGREE_OF_LATITUDE) < 1e-6


def test_the_same_point_is_zero_away_from_itself():
    assert geo.hav((59.881, 10.5566), (59.881, 10.5566)) == 0.0


def test_distance_is_symmetric():
    a, b = (43.20899, 27.87386), (42.4257, 27.6953)
    assert geo.hav(a, b) == geo.hav(b, a)


def test_longitude_shrinks_with_latitude():
    """A degree of longitude at 60 N is half of one at the equator, to within a metre."""
    equator = geo.hav((0.0, 0.0), (0.0, 1.0))
    north = geo.hav((60.0, 0.0), (60.0, 1.0))
    assert abs(north - equator / 2) < 1.0


def test_extra_elements_are_ignored():
    """Journey vertices are (lat, lon, epoch); several of the old copies unpacked exactly
    two elements and raised on a third."""
    plain = geo.hav((59.9, 10.5), (59.91, 10.5))
    with_time = geo.hav((59.9, 10.5, 1723200000), (59.91, 10.5, 1723203600))
    assert plain == with_time


def test_nautical_miles_are_metres_over_1852():
    a, b = (39.8793, 4.3071), (40.6141, 8.1926)  ## Mahon to Porto Conte
    assert geo.hav_nm(a, b) == geo.hav(a, b) / 1852.0


def test_the_mahon_sardinia_chord_is_the_known_183_nm():
    """The endpoints `find_gaps.py` reports for `Med 2023` s76. Note this is the straight
    chord between them, not the 534-point track, which is longer."""
    assert round(geo.hav_nm((39.8793, 4.3071), (40.6141, 8.1926))) == 183


def test_the_callers_names_all_resolve_to_the_shared_function():
    """`leg_export.hav` is metres, `find_gaps.hav` is nautical miles, and both are imported
    by name elsewhere in the tree. Neither may quietly become a private copy again."""
    from boattracker.nfl import find_gaps, leg_export

    assert leg_export.hav is geo.hav
    assert find_gaps.hav is geo.hav_nm
