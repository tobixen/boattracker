"""The suite must not read the developer's own configuration, whatever ran before it.

`conftest.py` pins a test boat and a nonexistent config file. `test_config.py` reloads the
config module repeatedly to exercise the layering, and until 2026-08-18 its teardown left
the module bound to `~/.config/boattracker/config.toml` — so every test module sorting
after it saw the author's real corpus. Named `zzz` so it runs last under any ordering that
is not randomised, and asserted rather than printed.
"""

import conftest

from boattracker import config


def test_the_config_module_is_still_the_test_one():
    assert config.CONFIG_FILE == conftest.ABSENT_CONFIG
    assert config.BOAT_NAME == 'Testboat'
    assert config.DATA == str(conftest.REPO)
