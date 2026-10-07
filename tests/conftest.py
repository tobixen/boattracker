"""Shared fixture paths, and a hermetic environment for the whole suite.

Two tests read a recorded sample rather than a synthesised one — the 12 726-point tracker
recording that pins the stop detector, and a real Raymarine export. Both used to be opened
by bare relative path, which quietly required pytest to be run from the repository root.
`DATA` resolves them from this file instead, so the suite runs from anywhere.

The environment below matters more. Several modules read boat identity at import time, and
since 2026-08-18 those settings have no defaults — they name a particular boat and a
particular person, so the software refuses to guess. Pinning them here does two things:
the suite runs on a machine with nothing configured, and it stops reading whatever the
developer happens to have in `~/.config/boattracker/config.toml`, which is exactly the
non-hermeticity that broke the config tests the day the corpus moved.

Git gets the same treatment, and is *forced* rather than defaulted, since an inherited
`GIT_CONFIG_GLOBAL` is exactly what it guards against. Without it the developer's
`~/.gitconfig` reached every test that runs git: a global identity hid a missing one until
CI ran the phone-import tests, and a `commit.gpgsign` or `core.hooksPath` would fail them
locally. The repository-pointing variables a git hook exports are dropped for the same
reason — a suite run from a pre-commit hook would otherwise act on this repository.
"""

import os
import pathlib

DATA = pathlib.Path(__file__).parent / "data"
REPO = pathlib.Path(__file__).parent.parent

ABSENT_CONFIG = str(REPO / "tests" / "no-such-config.toml")

os.environ.setdefault("BOATTRACKER_CONFIG", ABSENT_CONFIG)
os.environ.setdefault("NFL_BOAT_ID", "1234567890123456")
os.environ.setdefault("NFL_BOAT_NAME", "Testboat")
os.environ.setdefault("NFL_BOAT_SLUG", "testboat")
os.environ.setdefault("NFL_FROM_MAIL", "skipper@example.org")
os.environ.setdefault("SOLVEIG_DIR", str(REPO / "tests" / "no-such-diary"))
os.environ.setdefault("PHOTO_ROOT", str(REPO / "tests" / "no-such-photos"))

os.environ.update({
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "Test Author",
    "GIT_AUTHOR_EMAIL": "author@example.org",
    "GIT_COMMITTER_NAME": "Test Committer",
    "GIT_COMMITTER_EMAIL": "committer@example.org",
})
for var in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS"):
    os.environ.pop(var, None)
