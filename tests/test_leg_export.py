"""Tests for the segment reader.

`benelux.gpx`, and the since-deleted `france.gpx`, each contain a `<trkseg>` never closed. SOURCES.md
says a regex reader copes with that; it did not. Matching `<trkseg>.*?</trkseg>` silently
returns a *shorter* list, so every segment index after the unclosed one refers to the wrong
water — the quiet kind of wrong, since the export still builds and still looks plausible.
"""


from boattracker.nfl import leg_export


def gpx(body):
    return ('<?xml version="1.0"?><gpx version="1.1" creator="x"><trk><name>Track 1</name>'
            + body + "</trk></gpx>")


def seg(*points):
    return "".join(f'<trkpt lon="{lo}" lat="{la}"></trkpt>' for la, lo in points)


BOX = (48.0, 56.0, -4.0, 16.0)


def write(tmp_path, body):
    p = tmp_path / "t.gpx"
    p.write_text(gpx(body), encoding="utf-8")
    leg_export._cache.clear()
    return str(p)


def test_segments_are_found_when_every_trkseg_closes(tmp_path):
    path = write(tmp_path, f"<trkseg>{seg((54.0, 10.0), (54.1, 10.1))}</trkseg>"
                           f"<trkseg>{seg((53.0, 9.0), (53.1, 9.1))}</trkseg>")
    assert len(leg_export.segment(path, "Track 1", 0, bbox=BOX)) == 2
    assert leg_export.segment(path, "Track 1", 1, bbox=BOX)[0][0] == 53.0


def test_a_trailing_unclosed_trkseg_is_still_a_segment(tmp_path):
    path = write(tmp_path, f"<trkseg>{seg((54.0, 10.0), (54.1, 10.1))}</trkseg>"
                           f"<trkseg>{seg((51.0, 3.0), (51.1, 3.1))}")
    assert leg_export.segment(path, "Track 1", 1, bbox=BOX)[0][0] == 51.0


def test_an_unclosed_segment_does_not_shift_the_ones_after_it(tmp_path):
    # The real failure: without a closing tag the middle segment merges into its neighbour,
    # so index 2 silently becomes index 1's water.
    path = write(tmp_path, f"<trkseg>{seg((54.0, 10.0))}</trkseg>"
                           f"<trkseg>{seg((53.0, 9.0))}"
                           f"<trkseg>{seg((52.0, 8.0))}</trkseg>")
    assert leg_export.segment(path, "Track 1", 0, bbox=BOX)[0][0] == 54.0
    assert leg_export.segment(path, "Track 1", 1, bbox=BOX)[0][0] == 53.0
    assert leg_export.segment(path, "Track 1", 2, bbox=BOX)[0][0] == 52.0
