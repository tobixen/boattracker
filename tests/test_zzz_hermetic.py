"""The suite must not read the developer's own configuration, whatever ran before it.

`conftest.py` pins a test boat and a nonexistent config file. `test_config.py` reloads the
config module repeatedly to exercise the layering, and until 2026-08-18 its teardown left
the module bound to `~/.config/boattracker/config.toml` — so every test module sorting
after it saw the author's real corpus. Named `zzz` so it runs last under any ordering that
is not randomised, and asserted rather than printed.
"""

import subprocess

import conftest

from boattracker import config


def test_the_config_module_is_still_the_test_one():
    assert config.CONFIG_FILE == conftest.ABSENT_CONFIG
    assert config.BOAT_NAME == 'Testboat'
    assert config.DATA == str(conftest.REPO)


## Git: the developer's ~/.gitconfig and /etc/gitconfig must not reach the tests that run it.
## A global identity hid a missing one from the phone-import tests until CI ran them; a
## global commit.gpgsign or core.hooksPath would make them fail locally instead.

def git(*args, cwd):
    return subprocess.run(['git', *args], cwd=cwd, check=True, capture_output=True, text=True)


def test_git_reads_no_global_or_system_config(tmp_path, monkeypatch):
    # A --basetemp inside a work tree would otherwise add that repository's local scope.
    monkeypatch.setenv('GIT_CEILING_DIRECTORIES', str(tmp_path.parent))
    assert git('config', '--list', '--show-origin', '--show-scope', cwd=tmp_path).stdout == ''


def test_a_fresh_repository_can_commit_without_local_config(tmp_path):
    git('init', '-q', cwd=tmp_path)
    git('commit', '-q', '--allow-empty', '-m', 'x', cwd=tmp_path)
    assert git('log', '-1', '--format=%G?', cwd=tmp_path).stdout.strip() == 'N'
