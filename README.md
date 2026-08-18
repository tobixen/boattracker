# boattracker

I bought some chinese GPS tracker, installed it in my boat and got it to report positions
to my server. Now I'm doing stats on it, like pushing alarms to my cellphone if it's moved
or if the anchor drags while it's by anchor.

What grew out of that is two fairly separate things, and it is worth knowing which one you
are looking at:

* **The daemon** (`boattracker.tracker`) — listens for the tracker, parses its wire
  format, detects sailing, stops, mooring and anchoring, and raises an anchor alarm when
  the boat leaves where it was left.
* **The journey tools** (`boattracker.nfl`) — a much later and much larger body of work
  about *curating the recorded track*: merging Raymarine chartplotter geometry with the
  tracker's timestamps, finding the gaps and the backtracks, and keeping a
  [noforeignland](https://www.noforeignland.com/) journey honest.

## Installation

```
make install
```

(This auto-detects `uv`, `pipx`, or `pip` and does the right thing.)

For development, `make dev` instead — editable install with the dev dependencies, plus the
git hooks.

## Configuration

**The daemon needs no configuration at all.** The journey tools need to know which boat
they are working on, and there is deliberately no default for that — guessing would run
them against somebody else's journey and report success. So:

```
make config          # copies config.example.toml to ~/.config/boattracker/config.toml
```

Every setting can also come from the environment, which wins over the file — handy for
redirecting a single run:

```
TRACKER_DATA=/mnt/other python -m boattracker.nfl.find_gaps --mode partial
```

`config.example.toml` documents every key and marks the required ones. Two behaviours
worth knowing:

* **An unknown key is an error**, not a warning — a typo that silently did nothing would
  leave you believing the tools had been redirected when they had not.
* **A missing required setting fails when it is used, not when a module is imported**, so
  `--help` works on a machine with nothing set up.

## Usage

```
boattracker              # version, and an index of every tool
boattracker-daemon       # run the listening daemon
```

Each tool is a module with its own `--help`, and the docstring there is the real
documentation — most of them exist to avoid one specific trap, and say which:

```
python -m boattracker.nfl.find_gaps --help
python -m boattracker.nfl.find_backtracks --windows
python -m boattracker.nfl.merge_leg --fill --smooth ...
```

**Start with `IMPROVE-TRACKS.md`** if you are doing anything with the journey. It is the
runbook for the whole merge cycle and explains the order operations must happen in. Writes
to a live journey have no undo, so snapshot first.

## Features

* Auto-detects sailing, stops, mooring and anchoring.
* Automatic anchor alarm, sends a message when the boat is leaving the anchorage or the
  mooring.
* Makes statistics on sailing distances and stops, exports to JSON and log format
  (intended to be copied over to the captain's log).
* Makes a slightly compressed export of all points, in .json format.
* Reads Raymarine chartplotter GPX exports, Organic Maps phone exports, and the raw
  server-side tracker log.
* Finds gaps in a journey, and backtracks in it, at six different granularities.

## Repository layout

| | |
|---|---|
| `src/boattracker/` | the package: `tracker/` the daemon, `nfl/` the journey tools, plus `config.py` and `geo.py` |
| `tests/` | the suite, with its recorded fixtures in `tests/data/` |
| `scripts/` | `find-tracker-logs.sh`, the whole-disk search for raw tracker logs |
| `*.md` | the working documents — see below |

The **journey record is not in this repository either.** The upload ledgers, the 33
one-shot exporters recording how each past upload was built, and the hand-built chapter and
fix plans are one boat's record rather than software; they live at `[paths] journey`, by
default `~/solveig/journey`, and documents below are cited with a `journey/` prefix when
that is where they are.

The **track corpus is not in this repository** and never was in git — the GPX exports,
journey snapshots and raw tracker logs live wherever `[paths] data` points, which on the
author's machine is `~/solveig/tracks/boat/`. Only the two recorded samples the tests need
are here, in `tests/data/`.

The documents are where most of the knowledge is. `SOURCES.md` rates every date, time and
position source and says what each is weak at; `IMPROVE-TRACKS.md` is the runbook;
`journey/NFL-EXPORT-LOG.md` is the ledger of what was uploaded and the mistakes made doing it;
`RAYMARINE-GPX.md` covers that file format's quirks; `journey/PLACES.md` holds place coordinates;
`NFL-CHAPTERS.md` explains journey chapters; `journey/NFL-RETIRED.md` is the ledger of lines
removed from the site but kept on disk.

`TODO.md` is open work on the software. One boat's open *track* work — what is still
missing from its journey and what is recoverable — is a separate `TODO.md` in the journey
record, because it is a different job with a different audience.

## Work in progress

My intention is to refactor and document everything in such a way that it can be used by
other people than me and with other tracker solutions. I may even prioritize it if you
nag on me.

Be warned that a good deal of this is still specific to my setup: the wire format is that
of one family of Chinese trackers, and the journey tools assume Raymarine and
noforeignland. `TODO.md` tracks the work of separating the general from the specific.

## Web interface

The web interface at https://solveig.oslo.no/BoatTracker/Boat%20Tracker.html was set up by
my son. Its build output used to be committed here, in a `BoatTracker/` subdirectory; it
has been removed, because the deployed copy is newer than the one that was committed and
build artefacts do not belong in a source repository.

## Reinventing the wheel

I'm quite sure that most of the algorithms here have already been written by others
(particularly the map interface). The rational thing to do would have been to check up
what others have already done and try to stitch it together. Anyway it has been great fun
making this project.

## Contributing

See `CONTRIBUTING.md`. In short: `make dev` and write a test.
