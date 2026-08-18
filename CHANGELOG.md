# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project should adhere to [Semantic Versioning](https://semver.org/spec/v2.0.0.html) —
except that for pre-releases PEP 440 takes precedence.

## [Unreleased]

Nothing has been released yet; there are no tags. The entries below are the first pass at
making this a python project rather than a directory of scripts.

### Added

- `pyproject.toml`: a hatchling build with `hatch-vcs` versioning from git tags, ruff and
  pytest configuration, and `boattracker` / `boattracker-daemon` console entry points.
- A runtime config file, `~/.config/boattracker/config.toml`, layered under the
  environment variables: **environment > file > default**. `config.example.toml` documents
  every key. An unknown key is an error rather than a warning, because a typo that
  silently does nothing leaves the operator believing the tools were redirected.
- `boattracker.geo`: one haversine, in metres and nautical miles, replacing sixteen
  near-identical copies.
- `boattracker.config`: the data roots and boat identity, replacing hardcoded
  `/home/tobias/tracker` in thirty-one scripts.
- Test guards that no module in the package hardcodes a home path or leaves an interactive
  debugger call behind.
- `Makefile`, `CONTRIBUTING.md`, `.pre-commit-config.yaml`, `lychee.toml`, and GitHub
  Actions for tests (3.12–3.14) and link checking.
- `LICENSE` — the GPL-3.0 text the metadata has always claimed.

### Changed

- The track corpus moved out of the repository entirely (548 MB → 30 MB), to wherever
  `[paths] data` points, and the journey record with it.

- **Restructured to a `src/` layout.** The daemon is `boattracker.tracker` and the journey
  tools are `boattracker.nfl`; tests moved to `tests/`. Scripts that recorded how one past
  upload was built moved to `historic/`, which is not packaged, not linted and not
  expected to run — only their import lines were rewritten.
- `requires-python = ">=3.12"`. Python 3.10 and 3.11 both reach end of life on
  2026-10-31.

### Fixed

- `gpsparser.receive_data()` referenced `mypos`, a local of `main()`, so it would have
  raised `NameError` if anything had called it. Nothing did — it was superseded by
  `gt02a.Receiver` — and it is deleted. Found by the first ruff run.
- Files were opened and never closed in seventeen places across ten modules. They now go
  through `boattracker.files`, which also collapses the eight different spellings of "open
  a JSON file and parse it".
- `BlobError` is now raised `from` the underlying `ValueError`/`UnicodeDecodeError`, so a
  parse failure keeps the cause in its traceback.
- `test_parser.py` wrote 29 GPX, JSON and log files into the repository root on every
  run. It now runs in a temp directory. The daemon still writes them where it is started,
  which is intended.
- Non-hermetic tests: the suite read whatever `~/.config/boattracker/config.toml` happened
  to hold, and `test_config`'s teardown left every later test module bound to it.
- Required settings were resolved when a module was *imported*, so `--help` failed on a
  machine with nothing configured. They resolve when read now.
- `[paths] journey` could not be set without also setting `[paths] diary`, and blamed the
  wrong key when it was not.
- With no `[daemon] status_dir`, the anchor alarm read its override file from the working
  directory instead of treating it as absent.
- `read_text`/`write_text` took the locale's encoding rather than UTF-8.

### Removed

- `BoatTracker/`, the Godot/emscripten web UI build output. The deployed copy on
  `solveig.oslo.no` is newer than the one that was committed here. The 13 MB `.wasm`
  remains in git history.
- `requests` was imported by the daemon and never used, so it is not a dependency.
