"""Tests for import_phone_export.py — the Organic Maps export into a versioned copy.

The module's whole reason to exist is the superset check: an export truncated by a phone
reset or a reinstall must not silently overwrite the good copy, the way
`backup-documents.sh` refuses to publish a snapshot whose file count collapsed.
"""
import os
import subprocess
import zipfile
from collections import Counter

import pytest

from boattracker.nfl import import_phone_export
from boattracker.nfl.import_phone_export import (
    inner_kml,
    missing_timestamps,
    newest_export,
    shrinkage,
    when_timestamps,
)


def kml(whens, coords=None):
    tracks = '\n'.join('        <when>%s</when>' % w for w in whens)
    coords = '\n'.join('        <gx:coord>28.7 43.5 0</gx:coord>' for _ in range(len(whens) if coords is None else coords))
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<kml xmlns="http://www.opengis.net/kml/2.2" '
            'xmlns:gx="http://www.google.com/kml/ext/2.2">\n<Document>\n'
            '  <Placemark><gx:MultiTrack><gx:Track>\n'
            + tracks + '\n' + coords + '\n'
            '  </gx:Track></gx:MultiTrack></Placemark>\n</Document>\n</kml>\n')


A = ['2026-07-01T10:00:00Z', '2026-07-01T10:01:00Z']
B = A + ['2026-08-01T09:00:00Z']


def write_kmz(path, text, name='My Places.kml'):
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr(name, text)
    return str(path)


def test_inner_kml_reads_the_single_member(tmp_path):
    p = write_kmz(tmp_path / 'x.kmz', kml(A))
    assert '<when>' in inner_kml(p)


def test_inner_kml_refuses_a_kmz_holding_more_than_one_kml(tmp_path):
    p = tmp_path / 'two.kmz'
    with zipfile.ZipFile(p, 'w') as z:
        z.writestr('a.kml', kml(A))
        z.writestr('b.kml', kml(B))
    with pytest.raises(ValueError, match='exactly one'):
        inner_kml(str(p))


def test_when_timestamps_finds_every_fix():
    assert when_timestamps(kml(B)) == Counter(B)


def test_a_later_export_is_a_superset():
    assert not missing_timestamps(kml(A), kml(B))
    assert shrinkage(kml(A), kml(B)) == []


def test_a_truncated_export_is_refused():
    """The failure this check exists for: a phone reset losing recorded track."""
    lost = missing_timestamps(kml(B), kml(A))
    assert lost == Counter({'2026-08-01T09:00:00Z': 1})
    assert shrinkage(kml(B), kml(A))


def test_an_identical_export_is_accepted():
    assert shrinkage(kml(A), kml(A)) == []


def test_losing_one_of_two_identical_timestamps_is_noticed():
    assert missing_timestamps(kml(A + A[:1]), kml(A)) == Counter({A[0]: 1})


def test_losing_coordinates_while_the_timestamps_survive_is_noticed():
    assert any('gx:coord' in s for s in shrinkage(kml(A), kml(A, coords=1)))


def test_losing_a_placemark_is_noticed():
    old = kml(A).replace('</Document>', '  <Placemark><name>Home</name></Placemark>\n</Document>')
    assert any('Placemark' in s for s in shrinkage(old, kml(A)))


def test_newest_export_prefers_the_most_recent_across_directories(tmp_path):
    d1, d2 = tmp_path / 'newmi', tmp_path / 'pixel'
    d1.mkdir(), d2.mkdir()
    old = write_kmz(d1 / 'My Places.kmz', kml(A))
    new = write_kmz(d2 / 'My Places (2).kmz', kml(B))
    import os
    os.utime(old, (1000, 1000))
    os.utime(new, (2000, 2000))
    assert newest_export([str(d1), str(d2)]) == new


def test_newest_export_ignores_a_directory_that_is_not_there(tmp_path):
    d = tmp_path / 'newmi'
    d.mkdir()
    p = write_kmz(d / 'My Places.kmz', kml(A))
    assert newest_export([str(d), str(tmp_path / 'no-such-phone')]) == p


def test_newest_export_returns_none_when_there_is_nothing(tmp_path):
    assert newest_export([str(tmp_path)]) is None


## main(), end to end: one phone mirror each, a target repository, no real phone.

def git(*args, cwd):
    return subprocess.run(['git', '-c', 'user.name=t', '-c', 'user.email=t@t', *args],
                          cwd=cwd, check=True, capture_output=True, text=True).stdout


@pytest.fixture
def phones(tmp_path, monkeypatch):
    dirs = {'newmi': tmp_path / 'newmi', 'pixel': tmp_path / 'pixel'}
    for d in dirs.values():
        d.mkdir()
    monkeypatch.setattr(import_phone_export, 'PHONES', {k: str(v) for k, v in dirs.items()})
    return dirs


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / 'phone'
    r.mkdir()
    git('init', '-q', cwd=r)
    return r


def run(*args):
    return import_phone_export.main(list(args))


def test_each_phone_gets_its_own_file(phones, repo):
    write_kmz(phones['newmi'] / 'My Places.kmz', kml(A))
    write_kmz(phones['pixel'] / 'My Places.kmz', kml(['2026-09-01T12:00:00Z']))
    assert run('--out', str(repo), '--write') == 0
    assert when_timestamps((repo / 'newmi.kml').read_text()) == Counter(A)
    assert when_timestamps((repo / 'pixel.kml').read_text()) == Counter(['2026-09-01T12:00:00Z'])


def test_a_refused_export_leaves_the_target_byte_for_byte(phones, repo):
    (repo / 'newmi.kml').write_text(kml(B))
    before = (repo / 'newmi.kml').read_bytes()
    write_kmz(phones['newmi'] / 'My Places.kmz', kml(A))
    assert run('--out', str(repo), '--phone', 'newmi', '--write', '--commit') == 1
    assert (repo / 'newmi.kml').read_bytes() == before


def test_commit_records_the_export(phones, repo):
    write_kmz(phones['newmi'] / 'My Places.kmz', kml(A))
    assert run('--out', str(repo), '--phone', 'newmi', '--write', '--commit') == 0
    assert git('show', 'HEAD:newmi.kml', cwd=repo) == kml(A)


def test_an_identical_reimport_is_not_an_error(phones, repo, capsys):
    write_kmz(phones['newmi'] / 'My Places.kmz', kml(A))
    assert run('--out', str(repo), '--phone', 'newmi', '--write', '--commit') == 0
    assert run('--out', str(repo), '--phone', 'newmi', '--write', '--commit') == 0
    assert 'can now be deleted' in capsys.readouterr().out
    assert git('rev-list', '--count', 'HEAD', cwd=repo).strip() == '1'


def test_commit_refuses_a_target_that_is_not_a_repository(phones, tmp_path):
    out = tmp_path / 'not-a-repo'
    out.mkdir()
    write_kmz(phones['newmi'] / 'My Places.kmz', kml(A))
    assert run('--out', str(out), '--phone', 'newmi', '--write', '--commit') == 1
    assert not (out / 'newmi.kml').exists()


def test_the_kmz_is_not_declared_deletable_before_it_is_committed(phones, repo, capsys):
    write_kmz(phones['newmi'] / 'My Places.kmz', kml(A))
    assert run('--out', str(repo), '--phone', 'newmi', '--write') == 0
    out = capsys.readouterr().out
    assert 'can now be deleted' not in out
    assert "git -C %s add newmi.kml" % repo in out


def test_a_file_missing_from_the_working_tree_is_checked_against_head(phones, repo):
    write_kmz(phones['newmi'] / 'My Places.kmz', kml(B))
    assert run('--out', str(repo), '--phone', 'newmi', '--write', '--commit') == 0
    os.remove(repo / 'newmi.kml')
    write_kmz(phones['newmi'] / 'My Places (1).kmz', kml(A))
    os.utime(phones['newmi'] / 'My Places (1).kmz', (4000000000, 4000000000))
    assert run('--out', str(repo), '--phone', 'newmi', '--write') == 1
    assert not (repo / 'newmi.kml').exists()
