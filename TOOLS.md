# The journey tools

The index of every tool for merging Raymarine chartplotter tracks with the noforeignland
journey. The live ones are modules in `boattracker.nfl` — run them as
`python -m boattracker.nfl.<name> --help`, or `boattracker` for this list on the terminal.
The one-shot scripts are files in `historic/` and are not expected to run.

**A `journey/` prefix means the journey record** — one boat's ledgers, one-shot exporters
and hand-built plans, which are not software and left this repository on 2026-08-18. It is
`[paths] journey` in the config, `<diary>/journey` by default.

**Start with `IMPROVE-TRACKS.md`** — it is the runbook for the whole cycle and explains the
order operations must happen in. This file is only an index.

**Then read the precedence rule in `SOURCES.md`** (the owner's, 2026-08-12). It decides
what belongs on the journey and what comes off it: the Raymarine plotter carries the best
positions, the on-board tracker the best timestamps, and where both exist almost everything
else can be set aside — `Check in` first (its position is never accurate), then `NFL App`
(reliable enough, but not reliably *started and stopped*, so it under-covers passages and
sometimes records land journeys), with `Manual` yielding to real track. **Set aside means removed from the site, never destroyed**: export to
`nfl-retired/` with `reimport_journey.py` and verify it before deleting anything.

## Where the data is, and which boat it is

`boattracker.config` holds both. Three layers, highest first: **environment variable, then
`~/.config/boattracker/config.toml`, then the default.** `config.example.toml` in the
repository root documents every key; this is only the shape of it.

| setting | what it is | default |
|---|---|---|
| `[paths] data` / `TRACKER_DATA` | the track corpus: `nfl-export/`, `nfl-snapshots/`, `gpstracker-archive/`, `nfl-retired/` and the `*.gpx` exports | beside the code in a checkout, else the XDG data directory |
| `[paths] state` / `TRACKER_ROOT` | installation state — currently just the API token | the checkout, else the XDG config directory |
| `[paths] diary` / `SOLVEIG_DIR` | the diaries, where leg structure and chapter headings come from | **none — required** |
| `[paths] photos` / `PHOTO_ROOT` | the photograph archive `exif_index` and `photo_survey` index | **none — required** |
| `[paths] journey` / `TRACKER_JOURNEY` | one boat's record: the upload ledgers, the one-shot exporters, the hand-built plans | `<diary>/journey` |
| `[boat] id`, `name`, `slug` | the boat: the journey URL, the API referer the site checks, and the `<Boat> GPX track <name>` subject the importer matches on | **none — required** |
| `[mail] from` | the address registered with the noforeignland account | **none — required** |

**Required means required.** Anything naming a particular boat or a particular person has
no default and never will: guessing would run the tools against somebody else's journey and
report success. Using one that is not set raises an error naming the key, the file and the
environment variable — *importing* a module does not, so `--help` always works.

**`TRACKER_DATA` is the one that made `TODO.md`'s "Cleanup and split" possible** — the
corpus can leave this repository without the tools following it. One trap, recorded in that
file: `track_dates` dates tracks by reading the *filenames* in `nfl-export/`, so pointing
it at a location missing them does not fail, it silently disables the gap scans' date
filtering. Move the corpus whole.

`test_invariants.py` in `tests/` has the guard: no module in the package but `config.py`
may write an absolute home path.

`geo.py` is the other shared module — one haversine in metres (`hav`) and nautical miles
(`hav_nm`), reached as `LE.hav` and `FG.hav` by the tools that already imported them under
those names. It is **not** the solver `point.py` uses; that one is `geopy`'s ellipsoid
geodesic, and `TODO.md` explains why it has not been changed.

Two generations of script live here, and the difference matters:

* **Reusable tools**, written to be run again, with arguments and self-contained docstrings.
  These are the ones to use.
* **Session scripts**, which record how a particular result was reached. Paths are hardcoded to a
  session scratchpad and several read intermediate JSON that no longer exists. They are kept
  because their *leg tables* — which segment was dated to which day, and on what evidence — are
  the record of what was uploaded and why. Read the nearest analogue before writing a new one; do
  not expect them to run.

## Reusable tools

| Script | What it does |
|---|---|
| `nfl_auth.py` | the API token: capture, store, decode, probe. Explains why it cannot be scraped |
| `snapshot.py` | **the journey, as a file git can diff.** Fetches and reformats to one vertex per line, verifying the result parses back to the source before writing; `--raw` reproduces the `curl` blob byte for byte for the pre-write copies in `nfl-snapshots/` and never overwrites one, `--if-changed` refuses to write when only the calendar-derived counters moved |
| `import_sdcard.py` | deduplicates a fresh SD-card export against the corpus by `raymarine:GUID` |
| `track_dates.py` | date range per track and per segment, derived from `nfl-export/` filenames |
| `find_gaps.py` | **the gap finder.** Four modes; `partial` is the default and the one to trust |
| `leg_export.py` | shared GPX + MIME builder used by the exporters |
| `export_partial_runs.py` | fills a within-segment gap, dated from the journey's own vertex times |
| `tracker_archive.py` | **the 2021 raw feed.** Parses `gpstracker-archive/` into deduplicated days; `--gaps` finds the breaks, `--photos` checks it against the photograph index, `--write` writes one GPX per leg |
| `find_backtracks.py` | **backtracks, at two granularities.** In the drawn line: `hairpins` (a vertex reversing ~180°) and `retraces` (the line returning over ground it just covered), with elapsed time separating real revisits from artefacts. Between fixes: `connectors` (the chord the renderer draws to reach the next fix landing back on recent track), `swaps` (fix pairs whose timestamps look exchanged, measured by whether exchanging them shortens the path), `duplicates` (two fixes for one moment) and `windows` (a line covering a period the previous fix has already passed, read straight off the vertex timestamps — it catches the pairs that draw over *different* water, which the shape-based reports cannot see). The fix-level four are what find wrong ordering; no source file contains the offending edge |
| `exif_index.py` | photograph timestamp/GPS index; `--missing` lists days needing a location, `--locations` merges remembered ones |
| `delete_fixes.py` | bulk deletion by fixId |
| `prune_superseded_fixes.py` | removes hand-placed fixes that real track now covers |
| `dedupe_tracker_lines.py` | rebuilds part-duplicated tracker lines instead of deleting them |
| `rebuild_overlapping_fixes.py` | the same for hand-placed lines |
| `merge_leg.py` | **one fix, one leg.** Merges every timed vertex the journey holds for a leg into a single track — plotter positions, tracker times — reports the 1 nm+ gaps left, `--fill` splices local plotter track into them, `--write` emits the GPX keeping every vertex's own time |
| `replace_tracker_chords.py` | replaces a tracker straight line with plotter geometry; **excludes chords whose plotter cover is already on the journey** — those need the chord deleting, not the track sending again |
| `chapters_from_diary.py` | diary `#` headings into journey chapters; reconciles by start instant, so an edited heading is a rename in place and `--post` is safe to re-run (see `NFL-CHAPTERS.md`) |
| `add_chapters.py` | hand-built chapters no diary covers; the plan file is desired state, `--prune` reconciles |
| `add_fixes.py` | backdated position fixes, e.g. at a berth so a chapter boundary renders there. **Write the UTC offset into the plan** — a naive timestamp is read as local time |
| `omaps_export.py` | the Organic Maps phone export (.kmz/.kml) as timestamped fixes; absorbs the mixed namespaces and the phone's clock glitches |
| `timestamp_segments.py` | **plotter geometry + phone clock.** Order-aware dating of untimestamped `<trkseg>`s by Kendall's tau, distance-proportional interpolation, and `drop_off_planet()` for the segments the plotter records in Peru |


### On `find_gaps.py`

The question it answers keeps coming up and getting it wrong is easy, so read its docstring before
trusting an answer. In short:

* `partial` measures coverage **per edge**. The other modes measure per segment, and so cannot see
  a segment that is mostly uploaded with one stretch missing — which is the usual shape, and is
  how a 15 nm chord across land outside Marmaris survived two scans that reported 2024 clean.
* `uncovered` is **superseded**. On 2025-09 it disagrees with `partial` by 68 nm, in the direction
  of inventing gaps.
* Track dating is automatic via `track_dates.py`, but a track with too few dated segments cannot
  be scanned usefully. If an answer looks implausibly large, suspect the date map first.

## The one-shot exporters live elsewhere now

Every script that recorded how one particular past upload was built — the per-period
exporters and the session scripts — moved to the **journey record** on 2026-08-18,
`[paths] journey`/`historic/`, because they document what was done to one boat's journey
rather than how to do this work. There are 33 of them and they are **not expected to run**;
several cannot, their paths pointing at scratchpads deleted long ago.

Read the nearest one before writing a new exporter — their leg tables are the record of
which segment was dated to which day and on what evidence — but write the new one against
`export_partial_runs` and `merge_leg` above, which are the maintained way to do it.

Two of them are worth knowing about even though neither runs: `build_mail.py` is still the
clearest example of the MIME shape the importer wants (`merge_leg.eml()` is the working
version), and `audit_duplicates.py` carries two traps worth remembering — do not test for a
fix near a segment's *end point*, and do not measure against the existing lines' *vertices*,
which are about 550 m apart.

## Related documents

`IMPROVE-TRACKS.md` the runbook · `journey/TRACKS-2021.md` the 2021 photograph-driven job, which has no plotter data at all · `SOURCES.md` every date/time/position source and its
weaknesses · `RAYMARINE-GPX.md` the file format and the importer's quirks ·
`journey/NFL-EXPORT-LOG.md` what was uploaded, and the mistakes made doing it · `journey/PLACES.md` place
coordinates · `TODO.md`
