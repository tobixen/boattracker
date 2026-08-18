"""Reading and writing whole files, in one place instead of seventeen.

Seventeen sites across ten modules opened a file and never closed it —
`json.load(open(path))`, `open(path).read().strip()`, `json.dump(d, open(path, 'w'))`.
CPython closes those by refcount soon after, which is why it never visibly broke, but
`filterwarnings = ["error"]` turns the resulting `ResourceWarning` into a test failure the
moment a test touches one, and four of them did.

The duplication mattered as much as the leak: `TODO.md` asks for duplicated code to be
eliminated, and "open a JSON file and parse it" was written eight slightly different ways.
"""

import json

import pytest

from boattracker import files


def test_read_json_round_trips_what_write_json_wrote(tmp_path):
    path = tmp_path / 'x.json'
    files.write_json(path, {'a': [1, 2], 'b': 'x'})
    assert files.read_json(path) == {'a': [1, 2], 'b': 'x'}


def test_write_json_is_readable_by_plain_json(tmp_path):
    """Everything written here is also read by hand and by other tools."""
    path = tmp_path / 'x.json'
    files.write_json(path, ['6755398653151516'])
    with open(path) as f:
        assert json.load(f) == ['6755398653151516']


def test_read_text_returns_the_whole_file(tmp_path):
    path = tmp_path / 'x.gpx'
    path.write_text('<gpx>\n  <trk/>\n</gpx>\n')
    assert files.read_text(path) == '<gpx>\n  <trk/>\n</gpx>\n'


def test_read_text_can_replace_undecodable_bytes(tmp_path):
    """The Raymarine exports are not reliably utf-8, and a plotter export must not blow up
    the whole scan over one bad byte in a waypoint name."""
    path = tmp_path / 'x.gpx'
    path.write_bytes(b'<name>Sm\xf8rhavn</name>')

    with pytest.raises(UnicodeDecodeError):
        files.read_text(path)

    assert 'Sm' in files.read_text(path, errors='replace')


def test_write_text_writes_the_whole_file(tmp_path):
    path = tmp_path / 'x.gpx'
    files.write_text(path, '<gpx/>')
    assert path.read_text() == '<gpx/>'


def test_read_stripped_drops_the_trailing_newline(tmp_path):
    """The API token is stored one line to a file, and a newline smuggled into an
    `authorization:` header is a 401 that looks like an expired token."""
    path = tmp_path / 'token'
    path.write_text('  Bearer abc123\n')
    assert files.read_stripped(path) == 'Bearer abc123'


def test_nothing_is_left_open(tmp_path):
    """The point of the module. A leaked handle raises ResourceWarning, and the suite runs
    with `filterwarnings = ["error"]`, so this fails loudly if a helper regresses."""
    path = tmp_path / 'x.json'
    files.write_json(path, {'a': 1})
    for _ in range(3):
        files.read_json(path)
        files.read_text(path)
        files.read_stripped(path)
