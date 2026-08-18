"""Tests for pulling rendered journey geometry back out of noforeignland.

The case that matters is `test_line_geometry_is_read_from_the_linestring_not_the_point`:
the journey carries two features per fix and only the LineString holds the hand-placed
points. Reading the Point alone makes every fix look like a bare position with no track,
which is exactly what a naive read of the API does — and it is how ~94 vertices of the
owner's own map corrections nearly went unnoticed.
"""

from boattracker.nfl import reimport_journey as r


def doc(features):
    return {'geojson': {'features': features}}


def point(fid, lat, lon, ms, source='GPX Export'):
    return {'type': 'Feature',
            'properties': {'fixId': fid, 'layer': 'fixes', 'timeMs': ms, 'source': source},
            'geometry': {'type': 'Point', 'coordinates': [lon, lat, ms]}}


def line(fid, verts):
    return {'type': 'Feature',
            'properties': {'fixId': fid, 'boatId': 1},
            'geometry': {'type': 'LineString',
                         'coordinates': [[lo, la, ms] for la, lo, ms in verts]}}


MS = 1621260000000    # 2021-05-17T12:40:00Z


def test_line_geometry_is_read_from_the_linestring_not_the_point():
    d = doc([point(7, 58.5, 11.2, MS),
             line(7, [(58.4, 11.1, MS - 3000), (58.45, 11.15, MS - 1000), (58.5, 11.2, MS)])])
    e = r.fixes_and_lines(d)[7]
    assert e['point'] == (58.5, 11.2, MS)
    assert len(e['line']) == 3, 'the drawn track must come from the LineString feature'


def test_a_fix_with_no_line_feature_still_appears():
    d = doc([point(9, 57.0, 11.0, MS)])
    e = r.fixes_and_lines(d)[9]
    assert e['line'] == []


def test_range_filter_uses_the_fix_day():
    d = doc([point(1, 58.0, 11.0, MS), point(2, 58.0, 11.0, MS + 86400000)])
    got = r.in_range(r.fixes_and_lines(d), '2021-05-18', '2021-05-18')
    assert list(got) == [2]


def test_range_filter_drops_a_fix_with_no_timestamp():
    d = doc([point(1, 58.0, 11.0, None)])
    assert r.in_range(r.fixes_and_lines(d), None, None) == {}


def test_connector_is_stripped_only_when_it_repeats_the_previous_fix():
    prev = (58.4, 11.1, MS - 5000)
    l = [(58.4, 11.1, MS - 3000), (58.5, 11.2, MS)]
    out, stripped = r.strip_connector(l, prev)
    assert stripped and len(out) == 1


def test_connector_is_kept_when_the_line_starts_somewhere_else():
    prev = (59.9, 10.7, MS - 5000)
    l = [(58.4, 11.1, MS - 3000), (58.5, 11.2, MS)]
    out, stripped = r.strip_connector(l, prev)
    assert not stripped and len(out) == 2


def test_gpx_omits_time_for_epoch_zero_vertices():
    # Many 2023 vertices carry epoch 0; dating them to 1970 would be worse than no time.
    g = r.gpx('t', [(58.0, 11.0, 0), (58.1, 11.1, MS)], 'test')
    assert g.count('<time>') == 2          # one in metadata, one on the dated point
    assert '1970' not in g


def test_gpx_parses_and_keeps_every_vertex():
    import xml.etree.ElementTree as ET
    verts = [(58.0 + i / 100, 11.0 + i / 100, MS + i * 1000) for i in range(5)]
    g = r.gpx('t', verts, 'test')
    root = ET.fromstring(g)
    pts = root.findall('.//{http://www.topografix.com/GPX/1/1}trkpt')
    assert len(pts) == 5


def test_the_journey_request_identifies_itself_as_a_browser():
    """noforeignland answers 403 to urllib's default User-Agent.

    Not an authentication failure, though it reads as one - the first guess when this
    appeared was that a fresh token was needed. There is no token on the read path at
    all; the same URL returns 200 the moment a browser UA is sent. And the UA is
    `nfl_auth.UA`, not a fourth private copy of the same string.
    """
    from boattracker.nfl import nfl_auth
    req = r.journey_request()
    assert req.get_header('User-agent') == nfl_auth.UA
    assert 'boatId' in req.full_url
