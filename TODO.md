# TODO — boattracker

Open work on the **software**: the package, the tools, the test suite and the packaging.

**One boat's open track work is not here.** The 2023 delivery, the unfetched raw tracker
logs, the İçmeler disagreement, the backtrack sweeps and the rest moved to the journey
record on 2026-08-18, and are `TODO.md` there — `[paths] journey` in the config,
`<diary>/journey` by default. This file and that one refer to each other by name.

## Cleanup and split

**The blocker is gone as of 2026-08-17, and it was worth naming.** Thirty-one scripts
hardcoded `/home/tobias/tracker`, so moving the corpus would have left the tools reading a
path that no longer held the data — silently, in every case that globs rather than opens.
Boat identity was hardcoded too: `BOAT_ID` in two files, `S/Y Solveig` in two mail
builders, `map/boat/solveig/journey` as the API referer in five.

Both now come from **`boattracker.config`**, with every default reproducing exactly what
was hardcoded. `TRACKER_DATA` moves the corpus without the code following — verified end to
end, `track_dates` dates the same 70 tracks off a corpus pointed somewhere else — and
`TRACKER_ROOT`, `SOLVEIG_DIR`, `PHOTO_ROOT`, `NFL_BOAT_ID/NAME/SLUG` move the rest.
`test_invariants.py` pins it: nothing in the package but `config.py` may name a home path.

**Then, also 2026-08-17, it became a python project.** `src/` layout: the daemon is
`boattracker.tracker`, the journey tools are `boattracker.nfl`, tests are in `tests/`, and
the one-shot scripts that record how a past upload was built are in `historic/` — not
packaged, not linted, not expected to run, and only their import lines rewritten.
`pyproject.toml` (hatchling + hatch-vcs), ruff, pytest, pre-commit, a Makefile, CHANGELOG,
CONTRIBUTING, and GitHub Actions for tests and links. `config.example.toml` documents a
runtime config file layered under the environment: **env > file > default**.

`BoatTracker/` is gone. Note the premise was wrong: `tobixen/boattracker` on GitHub *is*
this project, a stale 2021-08-09 snapshot with `BoatTracker/` inside it, not a separate
repo for the web UI. The Godot source is in no repo; what was committed was build output,
and `solveig.oslo.no` serves a **newer** copy with icons that were never committed. The
13 MB `.wasm` remains in git history.

Four findings, all recorded rather than papered over:

* **`gpsparser.receive_data()` was a guaranteed `NameError`** — it referenced `mypos`, a
  local of `main()`. Nothing called it; it was superseded by `gt02a.Receiver` and is
  deleted. Found by the first ruff run, which is most of the argument for having ruff.
* **`audit_duplicates.py` does not run**, and had been listed as a reusable tool. It loads
  `{S}/aug2.json` from a Claude session scratchpad deleted long ago and its globs are
  pinned to the March 2025 batch — the identical fault `build_mail.py` is already
  documented for. Now in `historic/`.
* **Sixteen copies of the haversine**, byte-identical bar the unit and an `a[:2]` slice.
  The five in live tools are now `boattracker.geo`, aliased under the names callers
  already use (`LE.hav`, `FG.hav`, `timestamp_segments.haversine_nm`); the eleven in
  `historic/` stay. `UA` was duplicated between `nfl_auth` and `delete_fixes`, now one.
* **`requests` was a dependency that was never used** — imported by the daemon, never
  called. Not in `pyproject.toml`.

**Two things deliberately not done, so they are not mistaken for oversights:**

* **No `ruff format`.** Running it would rewrite ~1200 lines — the compact
  `import glob, os, re` style, the aligned coordinate tables — and bury the history of a
  codebase whose value is largely in what its comments explain. `ruff check` runs; the
  formatter does not, and `.pre-commit-config.yaml` says why.
* **No PyPI publish workflow.** The owner's call: the code is specific to one family of
  Chinese trackers, to Raymarine and to noforeignland, so claiming a package is premature.
  The name `boattracker` is free on PyPI when it is warranted.

**Known cleanups this uncovered and did not finish:**

* ~~**About twenty files are opened and never closed**~~ **Fixed 2026-08-17.**
  `boattracker.files` now holds `read_json`, `write_json`, `read_text`, `read_stripped`,
  `write_text` and `read_json_or_none`, and all seventeen sites across ten modules use
  them. That was as much about duplication as about the leak — "open a JSON file and parse
  it" was written eight slightly different ways.

  **It also produced the session's one genuine self-inflicted bug, which is worth
  recording.** `find_gaps.source_segments()` has a keyword parameter named `files`, so
  `from boattracker import files` was shadowed by the local inside the very function that
  needed it. Ruff saw nothing, all 329 tests passed, and the first real scan died with
  `'list' object has no attribute 'read_text'`. The module now imports those functions by
  name instead. **Nothing in the suite called `source_segments()` against real files** —
  every test stubbed the segment list or tested `eligible()` alone — so two tests were
  added that read a synthetic GPX off disk, and were confirmed to fail when the bug is
  reintroduced. The lesson generalises: the disk-reading entry points of these tools are
  the least-covered part of them.
* **Four bare `except:` clauses** remain in the live daemon (`gt02a`, `point`). Narrowing
  them to `except Exception` changes which signals propagate, so it wants doing
  deliberately rather than as a lint fix. `E722` is switched off in `pyproject.toml` with
  that note.

**The split is done, 2026-08-18.** Three steps, all of them:

1. **The corpus** — `~/solveig/tracks/boat/`, gitignored there, found via `[paths] data`.
2. **The journey record** — `~/solveig/journey/`, git-tracked there, found via
   `[paths] journey`. That is `journey/NFL-EXPORT-LOG.md`, `journey/PLACES.md`,
   `journey/TRACKS-2021.md`, `journey/DIARY-DISCREPANCIES.md`,
   `journey/NFL-RETIRED.md`, the 33 one-shot exporters that were `historic/`, the
   `plans/` files, and the one test that goes with them. It has its own README.
3. **The method documents stayed** — `IMPROVE-TRACKS.md`, `SOURCES.md`, `RAYMARINE-GPX.md`,
   `NFL-CHAPTERS.md`, `ORGANICMAPS-SYNC.md`, `TOOLS.md`. They say how to do this work
   rather than what was done to one boat, so they belong with the tools, and the package's
   own docstrings cite them 28 times.

The 29 cross-references were rewritten rather than left dangling: a `journey/` prefix now
means the journey record, and `README.md`, `TOOLS.md` and `IMPROVE-TRACKS.md` each carry a
one-paragraph legend saying so.

**What this repository is now:** the `boattracker` package, its 335 tests, six method
documents, and the packaging. 30 MB, no boat data, and nothing in it that only makes sense
for one boat except the defaults in `config.py` — which are defaults, and documented as
such in `config.example.toml`.

**Still open, and the honest remainder of the original three bullets:**

* **`~/solveig` now depends on the `boattracker` package.** `journey/historic/` imports
  `boattracker.nfl`, and `journey/tests/` needs it installed. That is tractable — it is a
  real installable package now rather than a sibling directory — but it is a dependency
  that did not exist before, and `journey/README.md` says so.
* **How this repository is published, settled 2026-08-18.**

  `tobixen/boattracker` on GitHub **is** this repository — a snapshot whose tip was
  `6678987`, 2021-08-09, and an ancestor of everything here.

  The full development history is **not** published, for two separate reasons. The 2026
  work was done against one boat's journey and **38 of its commit messages name a place or
  a date**, so filtering files would not have helped — the messages leak as much as the
  documents did. And the 2022-2024 history is 332 commits of which 68 say "bugfix", 29 say
  "tweak", and one is a chain of twenty-eight `fixup!` prefixes on a single message; there
  is nothing in them a reader could use.

  So `master` **is** the published history, squashed to three commits on top of what GitHub
  already has:

  | commit | commits squashed | what it says |
  |---|---|---|
  | first | 55, 2022-01 .. 2023-12 | the anchor alarm moving off Pushover, the anchorage logic, the web export rebuild |
  | second | 277, 2023-12 .. 2024-08 | the parser split into `point`/`gt02a`/`alarm`, and the first tests |
  | third | 165, 2026 | the journey tools, and becoming a python project |

  (Deliberately not named by SHA: these are rebuilt whenever a message is corrected before
  publication, and a table of stale hashes is worse than no table.)

  **73 commits published against 567 kept locally** on `backup-2026-08-18`, which is frozen
  and belongs to srv1. Every squashed tree stays reachable from that branch, so nothing is
  lost — only the messages are.

  **`master` is the public branch, so anything committed to it is published**, message and
  all. Write commit messages here as if a stranger will read them, because one can. Work
  about one boat's track rather than about the software belongs in the journey record and
  its own TODO.

  `master` tracks `github/master` and is a fast-forward ahead of it; the frozen backup is a
  fast-forward ahead of srv1's master. Neither has been sent — publishing is gated on human
  approval of every commit message, which is exactly why squashing 333 of them into 3 came
  first.

  **Audited.** Across the published commit messages the journey references are zero. The
  personal mail address is gone from the tree; two pieces of test data that used the real
  boat id and call sign now use fake ones. Publishing adds no blob over 200 kB. What
  remains is `Solveig` in comments explaining what a default used to be, left deliberately.

* **A Pushover user key has been public on GitHub since 2021-08-09**, and squashing did not
  and cannot change that — it is in `gpsparser.py` at `6678987`, inside the history GitHub
  already holds, which is not being rewritten. `u8qz7uu2fc64gonrjsbbkts67omba2`, removed
  from the working tree in the 2023-12 alarm rework when the notification path moved to
  send-mod-gearman.

  **The exposure is partial**: a Pushover *user* key cannot send anything on its own, it
  needs an application token too, and that token lived in a `secret` module which was never
  committed — checked across the whole history. So this is worth rotating at leisure rather
  than urgently, and it is recorded here because "the history has no credentials in it" was
  claimed earlier on the strength of a scan for credential-shaped *filenames*, which this
  would never have matched. Removing it would mean rewriting the already-public history and
  a force push, which buys little for a key that has been readable for five years.

  Also the point at which the `config.py` defaults naming one boat deserve a second look —
  they are documented as defaults in `config.example.toml`, but `Solveig`, the boat id and
  a personal mail address are the values a new user would first see.
* **`TODO.md` itself is still mixed** — this file is largely one boat's open track work
  (the 2023 delivery, the raw 2024 logs, the İçmeler disagreement) sitting in what is now a
  general repository. It is the last thing that has not been split, left deliberately:
  splitting it would scatter the open work across two files at the moment it is most
  useful to read in one.

This directory and repository now contains a mix-mash of different things, and possibly also quite some duplicated code.

* This repository should *only* contain general things, everything related to Solveig and Solveigs journey should be moved and committed to the ~/solveig directory
* There are lots of commits that haven't been pushed.  We can keep a backup of the git history in a separate branch, and maybe push it to a personal server, but I don't want stuff that is directly related to Solveigs track pushed to github.  This is not an absolute rule, it's no secret that this repository was made primarily for Solveig, and it's no secret where Solveig has been - it's just the fact that the repository is meant to be a general software project for the public.  Admittedly, quite some of the leftovers will be quite unique for my setup - code that will only work with the Chinese tracker I've been using, code only relevant for NFL users and Raymarine users, etc.
* It's needed to do a review of the whole project and write up a good README of what the repository contains and how to use the different parts.  Duplicated code should be eliminated.
* For the tracks, I feel that this belongs in the Solveig repository (~/solveig):
  * A complete backup of everything that is known about Solveig's track - including some depth data - and at least the same resolution as what's on the NFL site.  I don't have strong opinions on the format.  It should probably be split in chunks, like one file per month.  Please consider what makes sense.
  * Source data - deduplicated but otherwise unmodified - but possibly we should consider storing it in a separate directory.  Consider the size of everything - I'd like to keep the ~/solveig directory less than 1 GB.

## The pre-publication review, 2026-08-18

A clean-context review of the whole change set, before the first push to a public remote.
It found sixteen things; every one that mattered is fixed, and the ones below are recorded
because the *reason* they got through is more useful than the fixes.

**Three claims in this repository were false when written.**

* *"The personal mail address is gone from the tree."* It was gone from the `.py` and
  `.toml` files, which is what had been scanned. It was still in `IMPROVE-TRACKS.md`, in a
  worked `sendmail` example — twice — in an address that encodes a street name and house
  number. **The scan was the defect, not the address**; the same mistake earlier missed a
  Pushover key pasted into source, because that scan looked for credential-shaped
  *filenames*.
* *"Importing a module works with nothing configured; only using an unconfigured setting
  fails."* False for ten of the twelve journey tools, which resolved required settings at
  module scope, so `--help` died with an uncaught traceback — on the very commands
  `boattracker` tells the reader to run. Now true and pinned by `test_unconfigured.py`,
  which runs each module in a subprocess with a scrubbed environment. Doing it in-process
  proves nothing: `conftest.py` has already configured a boat.
* *"A test enforces that no module reintroduces [a boat or a person]."* The guard only ever
  looked for `/home/`. Nothing checked for a boat id, a call sign or a mail address. The
  claim is now true rather than softened — `test_the_package_hardcodes_no_boat_and_no_person`
  checks all four, reading code only, with docstrings found by `ast` rather than by pattern.

**Four real bugs, all introduced by the config work itself.**

* `[paths] journey` could not be set without `[paths] diary`. The fallback
  `os.path.join(_require('DIARY'), 'journey')` was passed as a *default argument*, so it
  was evaluated eagerly and demanded a key the caller had deliberately replaced — then
  blamed the wrong one in the error.
* `config.get()` decided whether to fall back by **substring-matching its own error
  message**. A sentinel subclass, `NotConfigured`, does it exactly now.
* With no `[daemon] status_dir`, the anchor alarm joined onto `''` and read
  `anchoring_time` **out of the daemon's working directory** — not "no override", which is
  what the adjacent comment and `config.example.toml` both promised.
* `read_text`/`write_text` took the locale's encoding while `read_json` pinned UTF-8, so a
  GPX round-trip depended on `LANG`.

**And the test suite was not hermetic after all.** `test_config`'s teardown cleared the
environment and reloaded — but `monkeypatch` had not yet restored `conftest.py`'s
variables, so the reload read the author's real `~/.config/boattracker/config.toml` and
left every later test module pointing at the real corpus. That is precisely what
`conftest.py`'s docstring claims to prevent. `test_zzz_hermetic.py` now asserts it.

**The lesson worth keeping** is about the shape of the mistakes rather than the count. All
three false claims were *checkable* and were not checked; two of the four bugs are Python
evaluating something earlier than intended; and the review that found them was worth more
than any amount of re-reading by the agent that wrote the code. `PEP 562`'s module
`__getattr__` also does not serve bare-name lookups inside the module's own functions —
ruff's `F821` caught that, twenty-nine times, immediately after the lazy attributes went
in.

**Not fixed, deliberately.** `SOURCES.md` names a private hostname and an on-disk path in
its source-provenance table. It is a factual note about where data came from, carries no
credential and no working recipe, and the owner's instruction was not to spend effort
scrubbing prose. The recorded test fixtures — a real day of tracker output and a real
plotter export — are likewise real positions on real dates, published knowingly.

## Known broken, and two optimisations deliberately not taken

~~**The two failing `test_parser.py` anchor-alarm tests and the untracked files in this
directory are another agent's job** as of 2026-08-14.~~ **Both fixed 2026-08-15**, see
"Why `test_parser.py` is slow" below. `test_raymarine.gpx.bak` was byte-identical to the
tracked `test_raymarine.gpx` and is deleted; `SplitGPX.pl` and `export_something.py` were
reviewed and **deleted 2026-08-15** — the Perl was superseded by the `<trkseg>` regex split
used in `historic/export_chain.py` and friends, and the Python was a throwaway `find_gap()`
driver whose parameters now live in `RAYMARINE-GPX.md` under "How a crop was actually
driven". The directory is clean of untracked files.

* ~~**Twelve `import pdb; pdb.set_trace()` calls are still live in the parser**~~ **Fixed
  2026-08-16.** Ten in `point.py`, two in `gt02a.py`. The class is now pinned by
  `test_invariants.py`, which fails on a `set_trace` or `breakpoint()` on any non-comment line
  of any shipped module — the guard that was missing when `2b13be7` removed four of the sixteen
  on 2026-08-04 and left the other twelve standing.

  **Each surviving check is now `point.invariant(ok, name, detail)`.** It counts into
  `point.invariants`, logs a warning **once** per check name so a 2.3 M fix run cannot drown in
  one repeated fault, and otherwise carries on — which is what a human typing `c` at the prompt
  did anyway, and none of these checks guards data that is unusable afterwards. Setting
  **`point.strict = True`** turns them back into `InvariantError` for a caller that would rather
  stop than continue; nothing sets it but the tests.

  **Raising unconditionally was considered and rejected.** `gt02a.Receiver.receive_blobs` calls
  `process_point` outside its own `try`, so an exception there propagates out of the connection
  handler: the daemon would go from surviving a broken invariant to dropping the tracker's TCP
  session on one. Counting is the only translation that fixes batch without breaking the daemon.

  **Four of the twelve were duplicates or dead and are simply gone.** `Path.split` tested the
  unstopped-stop-series condition twice, both times immediately after `_process_point_stop` had
  already tested it on the way out; case 2 of `_process_point_stop` tested it a third time at
  the same tick; and the copy in case 3/4 sat two lines below
  `self._prev_near_positions = MooringPath()`, so its length was always 0.

  The thresholds are named now — `MAX_NEAR_POINTS` 180, `MAX_PREV_NEAR_POINTS` 480,
  `MAX_STOP_POINTS` 500, `MAX_TIME_TRAVEL_SECONDS` 600 — so a test can lower them instead of
  having to synthesise five hundred points to reach one.

  **No measurable cost in the hot path**, which matters because `test_parser.py` budgets it.
  Eight paired runs of `data.split()` and the worst 16-point `process_point` window, wall clock
  and then `process_time`: 10.9–14.8 s and 0.67–1.11 s after, 10.4–14.3 s and 0.59–0.94 s
  before. The spread between repeats of the *same* code is several times any difference between
  the two, so this measures the laptop's load (2.6–4.0 throughout) and not the change — the
  trap already recorded at the end of this file. Medians came out slightly in the new code's
  favour, which is plausible — four redundant `len()` tests per point are gone — but is not
  worth claiming.

  **One correction to the original note, worth having:** the two `gt02a` calls were *not* in the
  batch path. `boattracker.nfl.tracker_archive` has its own `blobs()` splitter and calls
  `parse_blob` directly, so it never enters `parse_blobs`. The batch hazard is real all the same
  and lives in `point.py`: running the 2024 log through stop detection — which is what settles
  the İçmeler disagreement the journey TODO records — goes through `_process_point_stop`
  for every one of those fixes.
* **Two optimisations in `Point.distance_to` and `ts2dt`, both measured and both deliberately
  not taken** — see "Why `test_parser.py` is slow" below for the numbers. `great_circle` is
  **16x faster** than the `geodesic` now used and differs by 0.6 m on a 234 m leg, well inside
  tracker noise; and `ts2dt` re-parses string timestamps 154 816 times per test run, 18 % of
  the runtime, because `Point.ts` is a string. Both are the owner's call: **every distance
  recorded in the archive so far was computed the current way**, so changing the solver changes
  what future numbers mean relative to the old ones.

* ~~**`find_gaps.source_segments` disables its date filter when `--tracks` is given.**~~
  **Fixed 2026-08-15.** `eligible()` states the corrected rule, `replace_tracker_chords` and
  `merge_leg --fill` now pass the date range they already know, and `segment_eligible()` dates
  a *single segment* rather than the whole track — necessary because `Track 4` spans
  2023-12 .. 2024-05, so a track-level filter could never separate the slices that were being
  offered wrongly. **Opt-in** (`strict_dates=True`): switching it on inside the gap scans
  moves coverage totals through the `dedupe()` interaction, so those keep the filter they have
  always used. The `Track 4 s69` fill for 2024-04-03 is now never offered.

## Needs the owner

* **A diagnostic in `gt02a.parse_blobs` has never once run, and what it meant to ask is a
  guess.** The out-of-order reordering loop asks *"are we sure the order is wrong, or is it the
  timestamp that is wrong?"*, and one term of the condition is
  `points[-i-1].distance_to(points[-i-1])` — a point measured against **itself**, so it is
  always 0, `> 2` is always false, and the branch is unreachable. A third term,
  `.time_delta(...).total_seconds<120`, compares a bound method to a number and would raise
  `TypeError` if it were ever reached, which is independent confirmation that it never has.
  Presumably the first was meant to be `points[-i-2]` and the second `total_seconds()` — but
  that is a guess about what the check is *for*, so it was left exactly as written when the
  `pdb` behind it became a counted invariant on 2026-08-16. Two characters and a decision.
* **Nothing checks whether the drawn track crosses land**, and nothing ever has. **Scoped
  2026-08-15 on the owner's question; not built.** Every QA report here compares the journey
  against itself or against the plotter — all six `find_backtracks.py` modes, `find_gaps.py`,
  `audit_duplicates.py`, `prune_superseded_fixes.py`. **A coastline is the only external ground
  truth available**, and it would have caught outright the one defect two gap modes declared
  clean: the 15 nm chord drawn straight across the peninsula outside Marmaris (`Track 4` s95,
  `journey/NFL-EXPORT-LOG.md`, "Partial gaps").

  **The size of the job**, measured against `nfl-snapshots/snapshot-20260815-aug2026-final.json`:
  1644 lines, 45 599 vertices, **43 955 segments**, 16 310 nm. Two tests, both trivial for
  shapely's `STRtree`:

  * *vertex-in-land* — 45 599 point-in-polygon lookups; catches gross misplacement.
  * *segment-crosses-land* — the one that matters, since a chord has both ends in water. Only
    **2965 segments exceed 1 nm** (7040 nm), and those are the only ones that can cross a
    headland without a vertex landing on it. Ranked by crossed length, that list is short
    enough to read by hand.

  **What is on this laptop and what is not**, checked 2026-08-15: `shapely` 2.1.2 is installed;
  `geopandas`, `fiona`, `cartopy`, `rtree` and every shapefile reader are not. `pyshp` is the
  cheap way in — pure Python, no GDAL. **The land polygons are not on disk and cannot be
  committed**: GSHHG full resolution (~130 MB, `soest.hawaii.edu/pwessel/gshhg/`) or OSM
  `land-polygons-complete-4326` (~1 GB, `osmdata.openstreetmap.de`), both reachable (the
  sandbox has no network; unsandboxed does). **Natural Earth is useless at this scale** — its
  kilometre error would flag every Aegean passage.

  **The output has to be a ranked crossing distance, never a boolean**, because three classes
  of hit are correct by construction:

  * **connectors** — the renderer starts every line at the previous fix's position, so all
    **1642 of them, 1088 nm**, are straight joins. 2021-07-16's 23 nm across the feed break
    crosses whatever coast lies between, correctly.
  * **chords inside a leg** — the GSM dropouts, including the ~219.6 nm the journey TODO
    records under "Unrecordable".
  * **berths and inland water** — at GSHHG resolution a marina basin is land and its breakwater
    does not exist, so every Netsel, Varna and Bærum arrival scores; Varna Lake's canal and the
    Danube at Ruse are land in the data too.

  So each hit must be classified *connector*, *chord*, or **dense recorded track**, and only
  the third is a new finding — the first two should be cross-referenced against what
  `find_gaps.py --mode partial` already reports rather than listed again in new clothing. Two
  tolerances keep the noise down: ignore a point less than ~150 m inside land, and a crossing
  shorter than ~200 m.

  **What it cannot see:** duplicated or misdated water, which is over sea either way. The
  `Track 4` s95 slice dated nineteen days wrong would pass clean. This is a new axis, not a
  replacement for the backtrack reports.

  It would be `historic/find_land_crossings.py`, tests first. **Two calls for the owner:**
  whether it is worth building at all, and GSHHG against OSM polygons — 130 MB and coarse,
  or a gigabyte and metre-accurate.


## ~~Deferred: get the track data out of this repository~~ — done 2026-08-17

**The corpus now lives in `~/solveig/tracks/boat/`**, and the repository holds only the two
samples the tests need (`tests/data/test_raymarine.gpx`, `tests/data/test_data.raw`).

It was never in git — `.gitignore` already covered all of it — so this was a filesystem
move with no history to rewrite. **1139 files in directories plus 119 loose files,
537 515 132 bytes, verified identical on both sides of the move.** What went:
`nfl-export/`, `nfl-snapshots/`, `nfl-retired/`, `gpstracker-archive/`, `Raymarine/`, the
106 loose `*.gpx`, the 12 `*.gfx`, and the two `noforeignland-journey-*.json` caches.

`~/solveig/.gitignore` excludes `tracks/`, deliberately: half a gigabyte of GPX in a git
index would be there forever, and none of it changes retroactively. `~/solveig` is 630 MB
with it, inside the 1 GB the owner asked for.

**The tools find it through `~/.config/boattracker/config.toml`**, one key:

    [paths]
    data = "~/solveig/tracks/boat"

`TRACKER_DATA` overrides it for a single run. Verified by re-running the same gap scan
before and after: 124 runs, 632.6 nm, 139 undated segments both times, and `track_dates`
dates the same 70 tracks.

`tracks/personal/` exists and is empty. That is the other half of the split the owner
asked for — the phone's Organic Maps `My Places` export is **not** boat movement and must
never be merged into the boat track. Nothing has needed to live there yet; the exports have
been consumed straight from `~/Downloads`.

### Two things the move turned up

* **152 MB of exact duplication, still there and not deleted.** `Raymarine/My Data/` is
  the SD-card staging area, and seven `Tracks*.gpx` in it are **byte-identical** to the
  copies in the corpus root: `Tracks.gpx`, `Tracks202607.gpx`, `TracksA.gpx`,
  `TracksAdvt.gpx`, `TracksC.gpx`, `TracksCfn.gpx`, `TracksQ.gpx`. The root copies are the
  live ones — `find_gaps` uses `os.listdir`, which is flat, so nothing under
  `Raymarine/My Data/` is ever read. Deleting the seven halves the corpus and loses
  nothing, but it is the owner's data and the owner's call:

      cd ~/solveig/tracks/boat && cmp -s "Raymarine/My Data/Tracks.gpx" Tracks.gpx && echo same

* **`Raymarine/My Data/TracksSa.gpx` has never been scanned, and may hold real data.**
  6 MB, 342 segments, tracks named `Med 2023`, `Track 1`, `Track 3` and `Track 4` — the
  exact tracks the open 2023 and 2024 jobs above are about. It is not at the corpus root,
  so `os.listdir` has never seen it. `ToSantorini2024.gpx` beside it *is* covered, because
  that track also sits inside `TracksQ.gpx`, but nothing at root carries a track named
  `TracksSa`. **Whether it holds segments the corpus lacks is unknown and worth an hour:**
  copy it to the corpus root, re-run `find_gaps --mode partial`, and see whether the
  numbers move. `dedupe()` keys on the points themselves, so anything already present will
  collapse and only genuinely new segments will show.

## Smaller items

* **Unpushed commits on `master`.** Nothing has been pushed, by policy.
* **The suite is not hermetic against `~/.gitconfig`.** `conftest.py` isolates the
  environment, but the developer's git config still reaches the tests that run git. That
  is why the phone-import `--commit` tests passed locally and failed on CI, which has no
  git identity (fixed 2026-10-02 per fixture). A `commit.gpgsign` or a global hook would
  diverge the same way. Set `GIT_CONFIG_GLOBAL=/dev/null`, `GIT_CONFIG_NOSYSTEM=1` and
  `GIT_AUTHOR_*`/`GIT_COMMITTER_*` in `conftest.py`, and drop the fixture's local config.

## Why `test_parser.py` is slow — measured 2026-08-15

The suite's two failures are fixed, but the second one was a symptom worth writing down.

**`test_anchor_alarm` was a broken mock idiom, not a parser bug.** The test reset its mock by
assigning `alarm.call_count = 0`. Since python 3.12 `CallableMixin._increment_mock_call` sets
`call_count = len(call_args_list)` on every call, so the manual zeroing is overwritten and the
second assertion sees 2. `reset_mock()` now. `_process_anchorage` was always correct: exactly
one alarm per invocation on all four fixtures, with the severities the test expects.

**`test_parse_blobs_and_split` had two separate faults, and the bigger one was a bug in the
test, not slow code.**

* **The stopwatch was a module global that no test reset.** `check_time(30)` is written to bound
  `data.split()`, but `t` was last set by whatever `check_time()` ran before it — which in a
  full-file run is the *previous test*. So the 30 s budget was really measuring
  `test_anchor_alarm` plus `data.split()`, and with `pytest-randomly` deciding the order it
  sometimes did and sometimes did not. `data.split()` alone is **11.1–11.7 s against 30 s**.
  There is now a `mark()` that starts a measurement, called at the top of the test, so each
  budget bounds only what it names. **This was the dominant cause of the flake.**
* **The 0.8 s per-16-points budget is genuinely tight.** It peaks at **0.40 s on an idle
  machine** and **0.88 s at load average ~3** — always at `i=10800` or `i=11744`, the stop
  transitions described below. So a default `pytest` run on a busy laptop still fails, by
  design: `TRACKER_NOPERF=1` is the escape hatch and prints the overrun. **Do not raise the
  number instead** — a budget nudged upward whenever it complains stops detecting anything.

An earlier version of this note called the whole thing "a budget with about 2x headroom". That
is true of the 0.8 s one and was wrong about the 30 s one, which had no headroom for a reason
that had nothing to do with performance.

Where the ~27 s goes, from `cProfile` over the 12 726-point loop:

* **77 % is `Point.distance_to`** — 66 312 calls at ~205 µs. `geopy.distance.distance` is
  `geodesic`, Karney's ellipsoid solver in pure python via `geographiclib`. `great_circle` is
  **16x faster** (12.8 µs) and differs by 0.6 m on a 234 m leg, which is well inside the
  tracker's own noise. Not changed here, because every recorded distance in the archive was
  computed the current way.
* **18 % is `ts2dt`** — 154 816 `strptime` calls at 10.6 µs. Timestamps live as strings on
  `Point` and are re-parsed on every comparison.

The failures are not spread evenly. **Six single `process_point` calls take 160–400 ms each**
(i = 1697, 3898, 6363, 9061, 10797, 11741); everything else runs at 5–11 ms per 16 points. One
such call at i=9061 does **2 677 geodesic calculations**, 2 671 of them from
`ReduxPath.process_point` under `MooringPath.append` — that is `_process_point_stop` line 715,
`self._prev_near_positions.extend(self._last_near_positions)`, replaying a whole accumulated
near-position batch one point at a time when a stop ends. The peak scales with how long the
stop was, so the *last* spike is the worst one. That single call is what eats half the 0.8 s
budget, and it is the thing to optimise if the budget starts failing on an idle machine.

Two things that are *not* the cause, checked: no in-repo change — `point.py` was last touched
by `2b13be7` (gpx export signature, nothing in the hot path) and the budgets date from
`3cd078b`, 2024-01-21; and `geopy.distance.distance` has aliased `geodesic` since geopy 2.0 in
2020, so the budgets were written against the solver in use today.

The unforced `big_processes()` inside `process_point` never runs during these tests — its
`(now() - last point) > 60 s` guard rejects a 2023 recording — so the spikes are not it.

### The profiling harness, so it does not have to be re-derived

The scripts that produced every number above were throwaways in `/tmp` and are gone. This is
what they did; rebuilding takes a couple of minutes. Run from the repository root, with
`PYTHONPATH=.` if the script lives elsewhere.

**Whole-run profile** — gives the `distance_to` / `strptime` split:

    import cProfile, pstats, gt02a, alarm
    from point import BoatPosData
    from unittest.mock import patch
    alarm.enable = False
    data = gt02a.read_file('test_data.raw')

    @patch('point.BoatPosData.max_redux_points', 100)
    def run():
        b2 = BoatPosData()
        for i in range(len(data)):
            b2.process_point(data[i])
            if not i % 4000 or not i % 4003:
                b2.big_processes(force=True)

    cProfile.run('run()', '/tmp/prof.out')
    pstats.Stats('/tmp/prof.out').sort_stats('cumulative').print_stats(25)

Note the two `@patch`es. `max_redux_points` is what the test patches, and **without it the run
is not the one the budget bounds**. `alarm.enable = False` keeps the daemon's alarm path quiet.

**Finding the spikes** — time each `process_point` individually into a list and print the
twelve slowest by index. That is what showed six calls at 160–400 ms against a 5–11 ms
baseline, at i = 1697, 3898, 6363, 9061, 10797, 11741.

**Attributing one spike** — re-run with `pr.enable()` immediately before the call at the target
index and `pr.disable()` immediately after, then `Stats(pr).print_callers('point.py:39')` for
`distance_to` and `print_callers('point.py:303')` for `ReduxPath.process_point`. `print_callers`
rather than `print_stats` is the whole trick: it is what showed 2 671 of the 2 677 geodesic
calls arriving via `MooringPath.append`, which named `_process_point_stop`'s
`_prev_near_positions.extend(...)` as the cause.

**Two traps.** Measure the step in isolation — time `data.split()` directly rather than reading
it off `check_time`, because `t` is module-global and a budget can be measuring the previous
test (above). And the machine's load decides the answer: quote `uptime` alongside any timing,
since 0.40 s idle and 0.88 s at load average 3 are the same code.
