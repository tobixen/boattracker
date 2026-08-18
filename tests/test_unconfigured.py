"""Every shipped module must import, and every tool must print --help, with nothing set up.

This is the claim `config.py`'s docstring makes ("importing this module still works with
nothing configured and only *using* an unconfigured setting fails"), the claim
`config.example.toml` makes, and the claim `__main__.py` implies by telling the reader to
run `python -m boattracker.nfl.<name> --help`.

On 2026-08-18 it was false for ten of the twelve journey tools: they resolved required
settings at *module* scope, so importing them raised `ConfigError` and `--help` died with
an uncaught traceback. Nothing tested it, because every other test runs with the boat
pinned by `conftest.py`.

These tests deliberately run in a subprocess with a scrubbed environment. Doing it in
process would prove nothing: `conftest.py` has already configured a boat, and the modules
are already imported.
"""

import pathlib
import subprocess
import sys

import pytest

PACKAGE = pathlib.Path(__file__).parent.parent / 'src' / 'boattracker'

SCRUBBED = {
    'PATH': '/usr/bin:/bin',
    'HOME': '/nonexistent-home',
    'PYTHONPATH': str(PACKAGE.parent),
    'BOATTRACKER_CONFIG': '/nonexistent/config.toml',
}


def modules(subpackage):
    return sorted(p.stem for p in (PACKAGE / subpackage).glob('*.py')
                  if p.stem != '__init__')


def run(args):
    return subprocess.run([sys.executable, *args], env=SCRUBBED,
                          capture_output=True, text=True, timeout=120)


@pytest.mark.parametrize('name', modules('nfl'))
def test_a_journey_tool_imports_with_nothing_configured(name):
    r = run(['-c', f'import boattracker.nfl.{name}'])
    assert r.returncode == 0, f'importing it failed:\n{r.stderr[-800:]}'


@pytest.mark.parametrize('name', modules('tracker'))
def test_a_daemon_module_imports_with_nothing_configured(name):
    r = run(['-c', f'import boattracker.tracker.{name}'])
    assert r.returncode == 0, f'importing it failed:\n{r.stderr[-800:]}'


def test_the_index_command_runs_with_nothing_configured():
    r = run(['-m', 'boattracker', '--version'])
    assert r.returncode == 0, r.stderr[-800:]


@pytest.mark.parametrize('name', modules('nfl'))
def test_a_journey_tool_prints_help_with_nothing_configured(name):
    """`--help` must never be the thing that needs a boat configured."""
    r = run(['-m', f'boattracker.nfl.{name}', '--help'])
    assert 'ConfigError' not in r.stderr, (
        f'--help raised a config error:\n{r.stderr[-800:]}')
