# Contributing to boattracker

Contributions are mostly welcome (but do inform about it if you've used AI or other
tools). If the length of this text scares you, then I'd rather want you to skip reading
and just produce a pull-request in GitHub. If you find it too difficult to write test
code, etc, then you may skip it and hope the maintainer will fix it.

## Getting set up

```
make dev
```

That installs the package editable with its dev dependencies and installs the git hooks
(ruff on commit, the test suite and the link checker on push, conventional-commit checking
on the message).

`make test` runs the suite, `make lint` runs ruff.

## What to include

Every submission should ideally include:

- **Test code** covering the new behaviour or bug fix
- **Documentation** updates where relevant
- **A changelog entry** in `CHANGELOG.md` under `[Unreleased]`

## Commit messages

Please follow [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) and
write messages in the imperative mood:

- `fix: correct the arrival time on a leg whose last vertex is a stop`
- `feat: add a land-crossing check`
- `docs: update README`

Rather than:

- `This commit fixes the arrival time`
- `Added new check`

Note: older commits in this repository predate this convention and do not follow it.

## Things about this repository that will surprise you

**There is no `ruff format`.** `ruff check` runs, but the formatter is deliberately not
wired up: running it would rewrite about 1200 lines of a codebase whose value is largely
in what its comments explain. Match the surrounding style rather than reformatting.

**The journey record is a separate thing.** One boat's upload ledgers, its 33 one-shot
exporters and its hand-built plans live at `[paths] journey`, outside this repository —
they document what was done rather than how to do it. If you are adding an exporter, read
`boattracker.nfl.export_partial_runs` and `merge_leg`, which are the maintained way.

**Two test budgets measure wall clock** and will fail on a loaded machine by design.
`TRACKER_NOPERF=1` is the escape hatch and prints the overrun. Do not raise the numbers to
make them pass — a budget nudged upward whenever it complains stops detecting anything.
`TODO.md` has the measurements.

**Nothing may hardcode a path.** `boattracker/config.py` is the single place that knows
where the data is, and a test enforces that. See `config.example.toml`.

**Writes to the live journey have no undo.** Anything touching noforeignland should be
run against a snapshot first — `nfl-snapshots/` — and the runbook in `IMPROVE-TRACKS.md`
explains the order operations must happen in.
