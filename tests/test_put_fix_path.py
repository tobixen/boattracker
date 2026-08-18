"""Tests for writing a fix's line back over the API.

`PUT /api/v1/boat/fix/path` is the call the web map makes when the owner drags points on a
track. It is the first write in this project that does **not** go by email, which is what
makes it worth having: the site owner pays per volume for inbound mail.

It is also the most destructive call available. It does not append or patch - it
**replaces the fix's entire path with what is sent**. A path of one point, or an empty one,
silently discards a leg's whole geometry, and the only copy of hand-placed points is on the
site. So the tests here are mostly refusals.
"""

import json

import pytest

from boattracker.nfl import put_fix_path as P


def test_the_payload_matches_what_the_web_map_sends():
    """Captured 2026-08-05: [{"lat":58.308267,"lon":11.367783}, ...] as a `path` form field."""
    body = json.loads(P.path_field([(58.308267, 11.367783), (58.30873057262244, 11.36732161196354)]))
    assert body == [{'lat': 58.308267, 'lon': 11.367783},
                    {'lat': 58.30873057262244, 'lon': 11.36732161196354}]
    assert list(body[0]) == ['lat', 'lon'], 'key order follows the captured request'


def test_full_precision_survives():
    """The map sends 15 significant digits; rounding here would move points silently."""
    body = json.loads(P.path_field([(58.30873057262244, 11.36732161196354), (58.1, 11.1)]))
    assert body[0]['lat'] == 58.30873057262244
    assert body[0]['lon'] == 11.36732161196354


def test_an_empty_or_single_point_path_is_refused():
    """The failure that would destroy a leg, and it is one typo away."""
    for bad in ([], [(58.0, 11.0)]):
        with pytest.raises(ValueError, match='at least two'):
            P.path_field(bad)


def test_positions_off_the_planet_are_refused():
    for bad in [(91.0, 11.0), (58.0, 181.0), (-91.0, 11.0)]:
        with pytest.raises(ValueError, match='out of range'):
            P.path_field([(58.0, 11.0), bad])


def test_a_null_island_point_is_refused():
    """0,0 is what a missing coordinate looks like after a bad parse, not a position."""
    with pytest.raises(ValueError, match='0,0'):
        P.path_field([(58.0, 11.0), (0.0, 0.0)])


def test_the_request_is_a_multipart_put_with_the_two_captured_fields():
    cmd = P.curl_command(6755398652989521, [(58.0, 11.0), (58.1, 11.1)], 'TOKEN')
    assert '-X' in cmd and cmd[cmd.index('-X') + 1] == 'PUT'
    assert 'https://www.noforeignland.com/api/v1/boat/fix/path' in cmd
    forms = [cmd[i + 1] for i, x in enumerate(cmd) if x == '-F']
    assert forms[0] == 'fixId=6755398652989521'
    assert forms[1].startswith('path=[{"lat":')
    assert any('authorization: TOKEN' == h for h in cmd)


def test_the_token_is_never_placed_in_the_url():
    """It is a bearer credential for a live account; URLs land in logs and shell history."""
    cmd = P.curl_command(1, [(58.0, 11.0), (58.1, 11.1)], 'SECRET')
    urls = [a for a in cmd if a.startswith('http')]
    assert urls and all('SECRET' not in u for u in urls)


def test_a_repeated_consecutive_point_is_collapsed():
    """The rendered line duplicates its first vertex; the stored path does not.

    `reimport_journey` reports 21 vertices for fix 6755398652989521 with the Lilla Kornö
    point appearing twice, while the owner's own captured PUT sends it once. That gap is
    the leading connector, an artefact of drawing order. Feeding a rendered path back
    through this endpoint unchanged would add one duplicate per round trip, so exact
    consecutive repeats are dropped - they are zero-length segments and carry nothing.
    """
    body = json.loads(P.path_field([(58.30827, 11.36778), (58.30827, 11.36778),
                                    (58.31009, 11.37519)]))
    assert len(body) == 2
    assert body[0] == {'lat': 58.30827, 'lon': 11.36778}


def test_collapsing_repeats_cannot_empty_a_path():
    with pytest.raises(ValueError, match='at least two'):
        P.path_field([(58.0, 11.0), (58.0, 11.0), (58.0, 11.0)])
