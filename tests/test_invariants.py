"""The parser's own sanity checks, and the guard against them turning back into pdb calls.

An `import pdb; pdb.set_trace()` is survivable for the live daemon on a terminal, where a
human can look and type `c`, and fatal for a batch run over the archives, where it stops
dead waiting for input nobody is watching.  Commit 2b13be7 removed four of them; twelve
more were still live as late as 2026-08-15, with a 225 MB / ~2.3 M fix run over
`gpstracker.raw.2024` waiting on the other side of them.

So the checks are kept - they encode real knowledge about what the stop detector should
never see - but they now count instead of blocking.  `point.strict` turns them back into
exceptions for a caller that would rather stop than continue on a broken invariant.
"""

import datetime
import logging
import pathlib

import pytest

from boattracker.tracker import point
from boattracker.tracker.point import Path, Point

REPO = pathlib.Path(__file__).parent.parent
PACKAGE = REPO / 'src' / 'boattracker'


@pytest.fixture(autouse=True)
def clean_invariants():
    """Each test gets an empty counter and non-strict mode, whatever ran before it."""
    point.invariants.clear()
    point.strict = False
    yield
    point.invariants.clear()
    point.strict = False


def shipped_modules():
    """Every module in the package - i.e. everything that can run in batch.

    `historic/` is excluded on purpose. Those scripts are the record of how a past upload
    was built rather than code anyone runs, and several cannot run at all; a `pdb` call or
    a hardcoded path in one of them stops nothing.
    """
    files = [f for f in PACKAGE.rglob('*.py') if f.name != '_version.py']
    return [f for f in files if not f.name.startswith('test_')]


def test_no_interactive_debugger_in_the_shipped_modules():
    offenders = []
    for path in shipped_modules():
        for lineno, line in enumerate(path.read_text().splitlines(), start=1):
            if line.lstrip().startswith('#'):
                continue  ## a commented-out debugger call blocks nothing
            if 'set_trace' in line or 'breakpoint()' in line:
                offenders.append(f"{path.relative_to(REPO)}:{lineno}")
    assert offenders == [], (
        "interactive debugger calls in code that runs in batch: " + ", ".join(offenders))


def test_the_package_hardcodes_no_home_directory():
    """The blocker on TODO.md's "Cleanup and split", and the reason it is a test.

    Thirty-one scripts hardcoded `/home/tobias/tracker`, so moving the track corpus out of
    this repository would have left every tool reading a path that no longer held the data
    - silently, in the cases that glob rather than open.  `config.py` is exempt because
    knowing where things are is its whole job; nothing else in the package may say.
    """
    offenders = []
    for path in shipped_modules():
        if path.name == 'config.py':
            continue
        for lineno, line in enumerate(path.read_text().splitlines(), start=1):
            code = line.split('#')[0]
            if '/home/' in code or '/tmp/claude' in code:
                offenders.append(f"{path.relative_to(REPO)}:{lineno}")
    assert offenders == [], "hardcoded paths outside config.py: " + ", ".join(offenders)


def test_a_holding_invariant_records_nothing():
    point.invariant(True, 'never happens')
    assert point.invariants == {}


def test_a_broken_invariant_is_counted_and_does_not_raise():
    point.invariant(False, 'unstopped stop series', '501 points')
    point.invariant(False, 'unstopped stop series', '502 points')
    point.invariant(False, 'time-travelling point')
    assert point.invariants['unstopped stop series'] == 2
    assert point.invariants['time-travelling point'] == 1


def test_a_broken_invariant_warns_once_per_check(caplog):
    with caplog.at_level(logging.WARNING):
        for i in range(5):
            point.invariant(False, 'unstopped stop series', f"{500 + i} points")
    ## counted five times, logged once - a batch run must not drown in one repeated fault
    assert point.invariants['unstopped stop series'] == 5
    assert len(caplog.records) == 1
    assert 'unstopped stop series' in caplog.records[0].getMessage()


def test_a_broken_invariant_raises_in_strict_mode():
    point.strict = True
    with pytest.raises(point.InvariantError) as excinfo:
        point.invariant(False, 'unstopped stop series', '501 points')
    assert excinfo.value.check == 'unstopped stop series'
    assert excinfo.value.detail == '501 points'
    ## still counted, so a caller that catches it sees the same tally
    assert point.invariants['unstopped stop series'] == 1


def zigzag(count, metres=35, seconds=150):
    """A boat creeping back and forth between two positions `metres` apart.

    Slow enough (0.23 kn here) to stay under the 0.5 kn departure speed and inside the
    120 m stop radius, so every point lands in `_process_point_stop`'s case 2 and
    `_prev_near_positions` grows without the series ever counting as a stop.
    """
    start = datetime.datetime(2024, 1, 1, 12, 0, 0)
    step = metres / 111320.0  ## degrees of latitude
    return Path([Point((i % 2) * step, 0,
                       point.dt2ts(start + datetime.timedelta(seconds=i * seconds)))
                 for i in range(count)])


def test_split_counts_an_unstopped_stop_series_instead_of_blocking(monkeypatch):
    monkeypatch.setattr(point, 'MAX_STOP_POINTS', 4)
    path = zigzag(10)

    stops = path.split()

    assert not stops._has_stopped
    assert len(stops._prev_near_positions) > 4
    assert point.invariants['unstopped stop series'] > 0


def test_split_raises_in_strict_mode(monkeypatch):
    monkeypatch.setattr(point, 'MAX_STOP_POINTS', 4)
    point.strict = True

    with pytest.raises(point.InvariantError):
        zigzag(10).split()


def test_a_time_travelling_point_is_counted_not_debugged():
    path = Path([Point(0, 0, '2024-01-01T120000'),
                 Point(0, 1, '2024-01-01T130000'),
                 Point(0, 2, '2024-01-01T113000')])  ## an hour and a half backwards

    path.redux(min_dist=1, min_time=datetime.timedelta(seconds=1), max_points=99)

    assert point.invariants['time-travelling point'] == 1


## The commit that published this claimed "a test enforces that no module reintroduces
## [a boat or a person]".  That was overstated: the guard above only looks for `/home/`.
## These identifiers are the ones that were actually removed from the code on 2026-08-18,
## and this is what makes the claim true.
IDENTIFIERS = {
    'a boat id': r'\b4718293690613760\b',
    'a call sign': r'\bLJ6994\b',
    'a personal mail address': r'\b[A-Za-z0-9._%+-]+@bekkenstenveien[A-Za-z0-9.-]*',
    'a private hostname': r'\bsolveig\.oslo\.no\b',
}


def code_lines(path):
    """The module's lines with comments and docstrings blanked out.

    Prose is exempt from the guard below on purpose: several comments explain what a
    default *used to be*, and that history is worth keeping. Docstrings are found with
    `ast` rather than by pattern, because a heuristic that mistakes a string constant for
    a docstring would silently stop guarding it.
    """
    import ast

    source = path.read_text()
    lines = [line.split('#')[0] for line in source.splitlines()]
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
            continue
        doc = node.body[0] if node.body else None
        if (isinstance(doc, ast.Expr) and isinstance(doc.value, ast.Constant)
                and isinstance(doc.value.value, str)):
            for i in range(doc.lineno - 1, doc.end_lineno):
                lines[i] = ''
    return lines


def test_the_package_hardcodes_no_boat_and_no_person():
    """Names identifying one boat or one person belong in configuration, not in code."""
    import re

    offenders = []
    for path in shipped_modules():
        for lineno, code in enumerate(code_lines(path), start=1):
            for what, pattern in IDENTIFIERS.items():
                if re.search(pattern, code):
                    offenders.append(f"{path.relative_to(REPO)}:{lineno} ({what})")
    assert offenders == [], "identifiers that belong in configuration: " + ", ".join(offenders)
