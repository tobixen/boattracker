"""Tests for the whole-disk search for raw tracker logs.

The point of this script is to let an empty result be read as **evidence that the data is
not there**, which is a much stronger claim than "my grep found nothing". Every test here
guards that claim:

* the pattern must actually match the wire format, in plain files and inside archives;
* it must not match a neighbouring year, or a hit means nothing;
* it must survive a file with no newlines, because that is what the tracker writes — a
  whole day as one 460 kB line — and a big one of those is what killed grep on the first
  run, silently skipping up to 100 files;
* and it must refuse to report at all if its own pattern has stopped working.
"""

import os
import subprocess

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      'scripts', 'find-tracker-logs.sh')

## One real record, from gpstracker-archive/gpstracker.raw.1625236517.bz2. BR00 + YYMMDD +
## the A/V validity flag is the part the search keys on; the rest is carried so that a
## change to the pattern is tested against the true surrounding bytes.
REC = ('(028042516052BR00{ymd}A5953.1866N01035.3712E000.0195245200.9301000000L00000000)')


def record(ymd):
    return REC.format(ymd=ymd)


def run(tmp_path, year, *args):
    out = tmp_path / 'out'
    out.mkdir(exist_ok=True)
    proc = subprocess.run([SCRIPT, '-o', str(out), *args, year, str(tmp_path / 'disk')],
                          capture_output=True, text=True, timeout=120)
    hits = (out / f'tracker{year}-hits.txt').read_text().split()
    comp = (out / f'tracker{year}-compressed.txt').read_text().split()
    status = (out / f'tracker{year}-status.txt').read_text()
    return proc, [os.path.basename(h) for h in hits + comp], status


def disk(tmp_path, name, content, mode='w'):
    d = tmp_path / 'disk'
    d.mkdir(exist_ok=True)
    path = d / name
    path.write_text(content) if mode == 'w' else path.write_bytes(content)
    return path


def test_a_plain_file_holding_the_year_is_found(tmp_path):
    disk(tmp_path, 'gpstracker.raw.old', record('220924') * 3)
    proc, found, _ = run(tmp_path, '2022')
    assert proc.returncode == 0
    assert found == ['gpstracker.raw.old']


def test_a_neighbouring_year_is_not_reported(tmp_path):
    ## 2021 and 2023 differ from 2022 by one byte in the middle of the record. If the
    ## pattern were loose enough to catch them the whole result would be worthless.
    disk(tmp_path, 'y2021', record('210627'))
    disk(tmp_path, 'y2023', record('230627'))
    _, found, _ = run(tmp_path, '2022')
    assert found == []


def test_an_impossible_date_is_not_reported(tmp_path):
    ## Guards the month and day character classes. 22-19-40 is not a date, and matching it
    ## would mean the pattern is really just "BR0022 followed by digits".
    disk(tmp_path, 'junk', record('221940'))
    _, found, _ = run(tmp_path, '2022')
    assert found == []


def test_a_compressed_file_is_searched(tmp_path):
    import gzip
    d = tmp_path / 'disk'
    d.mkdir(exist_ok=True)
    with gzip.open(d / 'gpstracker.raw.gz', 'wt') as f:
        f.write(record('220924'))
    _, found, _ = run(tmp_path, '2022')
    assert found == ['gpstracker.raw.gz']


def test_a_large_file_with_no_newlines_is_searched(tmp_path):
    ## The real format: a day of fixes concatenated into a single line. grep buffers a
    ## whole line, so a big one of these is an out-of-memory kill - which xargs reports as
    ## "terminated by signal 9" and then carries on, losing the rest of the batch. The
    ## regression is silent, so the test has to be explicit.
    blob = record('220101') * 200 + record('220924') + record('220101') * 200
    assert '\n' not in blob
    disk(tmp_path, 'oneline.raw', blob)
    _, found, _ = run(tmp_path, '2022', '-L', '1024')   # force the large-file path
    assert found == ['oneline.raw']


def test_it_refuses_to_report_an_empty_result_if_its_own_pattern_is_broken(tmp_path):
    ## An empty hits file is the expected outcome and is meant to be trusted. That is only
    ## honest if the run proved the pattern still matches known-good bytes first.
    disk(tmp_path, 'nothing', 'no tracker data here')
    proc, found, status = run(tmp_path, '2022')
    assert found == []
    assert 'SELFTEST-OK' in status
    assert 'ALL-DONE' in status
    assert proc.returncode == 0


def test_a_run_that_never_finished_says_so(tmp_path):
    ## An empty hits file from a killed run looks exactly like an empty hits file from a
    ## clean one. ALL-DONE is the only thing separating them, so it must not be written
    ## before the passes are.
    disk(tmp_path, 'x', record('220924'))
    _, _, status = run(tmp_path, '2022')
    lines = [ln.split()[0] for ln in status.strip().splitlines()]
    assert lines.index('ALL-DONE') == len(lines) - 1
    assert 'PASS1-DONE' in lines and 'PASS2-DONE' in lines
