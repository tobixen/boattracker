# "Improve my tracks" — the runbook


**A `journey/` prefix means the journey record** — one boat's ledgers, one-shot exporters
and hand-built plans, which are not software and left this repository on 2026-08-18. It is
`[paths] journey` in the config, `<diary>/journey` by default.

The recurring cycle. The owner sails, the noforeignland app posts coarse fixes live over the
phone network, and later the SD card comes out of the chartplotter. Then: merge the fresh plotter
data with what is already on the site plus phone, diary and photographs; make sure everything is
held locally; delete what is superseded; upload the merged result.

This file assumes **no memory of previous sessions**. Read it, `SOURCES.md` and
`journey/NFL-EXPORT-LOG.md` before touching anything.

**The precedence rule governs the whole cycle** — it is in `SOURCES.md`, it is the owner's,
and it is dated 2026-08-12. In one paragraph: the record on noforeignland should be as
complete as possible, every source merged, the most reliable kept and the less reliable not
used there. **The Raymarine plotter carries the best positions; the on-board tracker carries
the best timestamps.** Where both exist, almost everything else can come off the site after a
quick QA that the two agree — `Check in` first (its position is never accurate), then
`NFL App`, with `Manual` yielding wherever real track exists. The app is *not* imprecise;
it is **not reliably started and stopped**, so it under-covers passages and sometimes keeps
recording ashore, drawing a car or train journey as if it were one.

**And "comes off the site" never means "is destroyed."** Export it to `nfl-retired/` with
`boattracker.nfl.reimport_journey` and verify the GPX *before* deleting. A snapshot preserves
geometry but cannot be put back; the GPX can. This is step 4 below and it is not optional.

**Where each rule lives**, since they were settled at different times and one document cannot
sensibly hold all of them:

| Rule | Where |
|---|---|
| Which source wins on position, and which on time | `SOURCES.md`, "The precedence rule" |
| What each source is good and bad at, per source | `SOURCES.md`, same section |
| Nothing is destroyed — export before deleting | `SOURCES.md`, and step 5 below |
| What a fix *is*, and that its time is the arrival | below, "What a fix actually is" |
| How long a fix should be — **one leg** | below, "How long should a fix be?" |
| When to replace an old track | below, same section |
| Manual one-point fixes: mid-track vs between tracks | below, and `SOURCES.md` |
| Email or API, and why | below, "Which write path" |
| Traps that have already caught someone | below, "Traps" |
| Where a chapter renders, and how to move it | `NFL-CHAPTERS.md` |
| What was uploaded, and every mistake made doing it | `journey/NFL-EXPORT-LOG.md` | For 2021 read `journey/TRACKS-2021.md` instead of this:
there is no plotter data for that year, so the method is different. `RAYMARINE-GPX.md` has the file format,
`journey/PLACES.md` the place coordinates.

---

## What a "fix" actually is — read this before anything else

**A fix is one timestamp for a whole track.** Not a position report: a single instant that
noforeignland hangs an entire `LineString` on, and that line may cover minutes, hours, days
or weeks of sailing. Everything confusing about this project follows from that one fact, so
it is worth stating plainly before the runbook starts.

Consequences, all of which have cost real time here:

* **The fix's own timestamp is the *arrival*** — the end of the line, not its start. A leg
  uploaded with one timestamp says "the boat got here then", and says nothing about when it
  left.
* **The renderer joins fix to fix.** Every line is drawn starting from the *previous* fix's
  position, so the order of fix timestamps is the order the map is drawn in, whatever the
  vertices inside the lines say.
* **A long fix is a lie by omission.** One timestamp on a 236 nm, 112-hour run (Brest → La
  Rochelle, `journey/NFL-EXPORT-LOG.md`) puts the whole passage on one instant, so no day inside it
  can be dated and the mileage lands on the wrong date.

### How long should a fix be? **One leg** — the owner's preference, 2026-08-14

**One fix, one leg, with a timestamp on every vertex.** A leg runs **from one significant
stop to another**. That is the target when correcting old tracks, and it replaces both the
two-hour target below and the "a day as one fix" fallback: a day may hold several legs, or a
leg may run over midnight, and the leg is the unit that means something.

**What counts as a significant stop is a judgement, and the diary is the record of it.**
Significant stops should be noted in the diary headers. It is **not fully possible to spot
one algorithmically** — some attempts exist in the old tracker code, `point.py`'s
`BoatPosData.split()`, which classifies `sailing` / `mooring` / `anchoring` from a distance
and speed threshold (30 m / 120 m / 0.5 kn) — but treat that as a shortlist, never as the
answer.

Two cases where a stop still needs something on the journey:

* **A long stay in harbour** — put a **manual position fix before departure**. It costs one
  point and it is the only way to record *when the boat left*, since every fix timestamp is
  an arrival.
* **A long stay at anchor where the boat moves a lot** — it may be worth exporting some track
  data, because the swinging is real movement and a single point misrepresents it.

**When to replace an old track**, then, is answerable:

* **one fix spans more than one leg** — it is welding two passages and a stop into a single
  timestamped line; or
* **the old fix has significant data gaps** — the shape is there but the substance is not.

Anything else can be left alone. Replacing a track that is already one leg with no gaps buys
nothing and costs a message.

### Which write path — and it is not a matter of taste

**Replacing an old track is cheap.** Do not weigh a replacement as though it were risky. The
constraints are message volume and the truth of the data, never the act of replacing.

There are two ways to change the journey, and one question decides between them:

> **Does the new geometry carry *recorded* vertex times?**

* **Yes → the email gateway.** Carrying `<time>` on every trkpt is the *only* thing the
  importer does that the API cannot. That is what it is for.
* **No → the API**, always. `add_fixes.py` to place the fix, `put_fix_path.py` to set its
  geometry. If the times are assigned or interpolated rather than recorded, mail buys nothing
  and costs the site's owner money — he pays his provider per inbound message, and this
  project has already sent hundreds.

So a leg built from tracker vertices has real times and earns a message; one built from
plotter geometry alone does not. **`put_fix_path` sends `{lat, lon}` only**, so rewriting a
path over the API silently discards whatever vertex times that line held — check what you are
about to overwrite (`reimport_journey.py`) before using it on a timed line.

Volume also bounds how fine a leg can usefully be *by mail*: a whole day as one message is
what the gateway can bear, so where the leg rule wants something finer, use the API.

Week-long fixes are believed to be **all split by now**; if one turns up, it is a leftover
and should be cut to one leg.

### Superseded: the two-hour target, and why the rationale collapsed

Kept because the reasoning is instructive, not because it is in force. The two-hour target was
set on 2026-08-12 on the assumption that **a fix carries only one timestamp**, so a long fix
would leave everything inside it undatable. That assumption is **false**: the journey stores a
time on each *vertex* too — **25 434 of 34 326 interior vertices carry one**, 74 %. A long leg
is therefore still datable minute by minute along its length. The owner withdrew the target the
same day it was written down and replaced it two days later with the leg rule above.

The lesson that outlives it: **check what the data actually holds before designing around what
you assume it holds.**

### Manual one-point fixes: one must go, the other should stay

Both are `source: Manual` and they look identical in every listing. The difference is
**where the fix sits relative to the tracks around it**, and it decides opposite actions:

| Where it sits | What to do | Why |
|---|---|---|
| **In the middle of a track** | **must be deleted** | the renderer draws to it and then back out to continue the line, so it manufactures a **backtrack** on the map. The 2022-07 Polish coast is the worked example — bare fixes added there laid straight 2-vertex chords across real track and were deleted again (`NFL-CHAPTERS.md`) |
| **At a harbour or anchorage, between two tracks** | **should be kept** | it is not competing with any line, and it carries extra information — above all a **departure** timestamp, which a fix-per-track model otherwise cannot express, since every fix time is an arrival |

That second row is why `Manual` is not simply ranked below track data in the precedence rule
(`SOURCES.md`): a manual fix between legs is recording something no track can.

### Creating a track under the current rules

**First add a manual fix, then attach the track data to it.** That is the order, and it is
also the route that avoids the email importer entirely:

```
python3 boattracker.nfl.add_fixes --plan plan.json      # the fix: position + arrival instant
python3 boattracker.nfl.put_fix_path --fix-id <fixId> --path path.json   # the geometry
```

`put_fix_path.py` **replaces the whole path** — it is not an append — and backs the old one
up first. Import by email remains the only way to create a fix *and* its geometry in one
step, which is exactly why this two-step route exists.

---

## Traps, all of which have already caught someone here

Consolidated 2026-08-14 from a long QA session. Each of these cost real time, and several
cost *the same* time twice.

**"Better data exists" is not the same as "better data is missing from the journey."** Asked
three times, wrongly, in three different tools. `replace_tracker_chords.py` offered to fill
chords whose plotter cover had gone up months earlier — its "fragments" were its own past
output. A re-date of a slice onto 2024-04-22 turned out to duplicate three points that day
already held to within 1 m. **Before adding or moving geometry, ask whether the destination
already holds it.** `already_on_journey()` asks it for chords; nothing asks it for you
elsewhere.

**Merging does not resolve a contradiction between sources — it moves it inside one line.**
Two records disagreeing about where the boat was produce a jump *between fixes*, which
`find_backtracks.py` reports; merge them and the same error is *inside* a line, where no
report can see it. `merge_leg.implausible_steps()` exists for exactly this and runs on every
merge. 2024-04-03 produced steps of 61.7 and 73.3 kn that way.

**Continuity in time is not continuity in track.** Two segments 53 seconds and 0.36 nm apart
looked like one line split across two dates. They came from different plotter segments
entirely; the join was coincidence.

**Plotter timestamps are assigned, so they are what breaks.** The chartplotter records no
time at all — every Raymarine timestamp here was put there by an export script or by hand.
When speeds come out impossible, that is where to look: on 2024-04-03 every implausible step
had a Raymarine end, five of six had Raymarine at *both*, and none was tracker-to-tracker.

**A fix that only partly overlaps a leg can neither be deleted nor merged**, or the same
water lands in two places. Check the boundary fixes before choosing a leg's window; on
2024-02-24 two of them held the anchorage stay and the following night.

**Coverage must be measured against one leg, not a pool of every nearby edge.** A pool lets a
short line be "covered" by stitching together legs recorded hours apart. Five of eight `NFL
App` lines looked superseded that way; measured against the single best leg, three were.

**An average speed hides its shape.** Two fixes looked like four and five days of anchor
swing at 0.02 kn. One was a single stray vertex welded to a real 23-minute manoeuvre; the
0.02 kn was the gap between them, not the boat.

**A naive timestamp is read as *local* time.** `add_fixes.py` applies `TZ` to a plan
entry with no offset, so `2026-07-26T07:33:00` meant to be UTC becomes 07:33 CEST — two
hours late, on every fix in the batch. The dry run prints the zone; read it. Write
`%Y-%m-%dT%H:%M:%S+00:00`.

**Export filenames are not cosmetic — they are the date map.** `track_dates.py` reads
`nfl-<date>-track<N>s<M>` out of `nfl-export/`, and a batch named any other way leaves its
tracks undated, which makes every later gap scan measure their water against the whole
journey. Nineteen misnamed files moved 2023's gap figure by 29 nm.

**A filter that takes a majority vote can be captured by the fault it is filtering.** The
plotter's Peru episode became *seven* segments in `Track 65` against four real ones, so a
median over segment centroids elects Peru. Weight by points: 335 against 9650.

**The importer thins what you send.** 22 trkpts went up as a 20-vertex line — consecutive
near-duplicates are dropped. Do not expect a vertex count to survive a round trip.

**`prune_superseded_fixes.py` needs reading, not piping.** It has needed two guards in two
days — chapter-boundary fixes, then only-fix-of-its-day — because a fix that is *doing a job*
looks identical, by a coverage test, to one that is merely redundant. Assume there are more.

## 0. Credential

```
python3 boattracker.nfl.nfl_auth --check
```

Uploads need no credential at all — import is by email. Only **deletion** needs the token. If
the check fails, `nfl_auth.py`'s docstring says how to capture one; it cannot be scraped from
cookies, and the reasons are documented there rather than rediscovered.

## 1. Snapshot before anything

```
python3 -m boattracker.nfl.snapshot --raw \
        --out nfl-snapshots/snapshot-$(date +%Y%m%d-%H%M)-before.json
```

That is the working copy, one per write-session, and it stays out of git — byte for byte the
blob `curl` used to write, which is still the fallback if the package is not installed.
`--raw` refuses to overwrite an existing file, since a second session on the same day would
otherwise replace the only record of what the first one deleted:

```
curl -s 'https://www.noforeignland.com/api/v1/boat/journey?boatId=4718293690613760&showStories=true' \
     -o nfl-snapshots/snapshot-$(date +%Y%m%d-%H%M)-before.json
```

**Afterwards, when the writes are done and verified, update the tracked snapshot too:**

```
python3 -m boattracker.nfl.snapshot --if-changed
```

which rewrites `<journey>/journey-snapshot.json` in the line-oriented form and is meant to
be committed. That file is what makes `git log -p` able to answer "when did this fix
disappear, and what else moved when it did" — the question `NFL-EXPORT-LOG.md` otherwise has
to be written by hand to answer. `--if-changed` keeps a run that found nothing from
producing a commit consisting solely of the two calendar-derived counters.

Non-negotiable, and not merely belt-and-braces:

* Deletion has no undo. A deleted fix can only be restored by re-uploading its GPX.
* **The snapshot is the only copy of hand-placed map corrections.** Points added to a line by
  hand in the web map exist nowhere locally. The 2025-08 gap-fill chain was uploaded with 5
  points and rendered 16 — that difference was the owner's work routing the line off the land,
  and it was destroyed by a deletion and recovered only because a snapshot had been taken
  minutes earlier. Before deleting any fix, diff its rendered vertex count against the GPX that
  was uploaded; a higher count means hand-editing that must be preserved.
* Journey vertices carry `[lon, lat, epoch_ms]`, and those per-vertex times are the best dating
  evidence available for 2024 onwards. Losing them loses more than geometry.

## 2. Import the fresh card

Copy the export off the SD card into this directory, then:

```
python3 boattracker.nfl.import_sdcard
```

Deduplicates against the existing corpus by `raymarine:GUID`. Expect overlap: the plotter keeps
old tracks, so most of a fresh export is already held. Add the new file to the inventory table in
`RAYMARINE-GPX.md`.

Watch for tracks at **~10 000 points** (9981, 9985, 9987 have all been seen). That is the
plotter's cap, and a full track means recording *stopped* rather than rolled over — the gap that
follows begins where the boat was under way, unlike a switched-off-plotter gap which begins at a
berth.

## 3. Find what is missing

```
python3 boattracker.nfl.find_gaps --from <lo> --to <hi> --mode partial --min-nm 0.5
```

`partial` is the mode to trust. The others (`uncovered`, `journey-gaps`, `chords`) are faster and
coarser, and two of them declared 2024 "clean" while a 15 nm chord cut across the peninsula
outside Marmaris — because they judged coverage **per whole segment**, and the segment in
question was 78% present. Ask per edge.

Source tracks are date-filtered automatically by `track_dates.py`, which derives ranges from the
dates already encoded in `nfl-export/` filenames. So **every export improves the next scan**.
Two limits to know:

* Tracks with few dated segments cannot be scanned. `Track 1`, `Track 3` and `Track 7` are in
  that state; run against them the scan claimed 2002 nm missing for 2024, nearly all artefact.
  If a scan reports implausibly much, suspect this before believing it.
* `--tracks` overrides the filter, `--no-date-filter` disables it. Without any filter a May 2024
  gap gets "bridged" by a July 2026 track.

## 4. Date the new material

Ranked; use the best available and say in the upload description which was used. `SOURCES.md`
has the full inventory with each source's weakness.

1. **Engine log** — explicit UTC with hours and total miles. Sparse but decisive.
2. **Journey vertex timestamps** — `export_partial_runs.py` brackets a missing run by the
   journey's own clock either side of it. Works from 2024 on. **Fails for 2023**, where most
   vertices carry epoch 0.
3. **Diary headings** — an ordered place chain per day, which fixes the date and the leg count
   before any track is examined. The single most reliable dating tool in this project.
4. **Photographs** — `exif_index.py`, exact to the second. Times are stored raw; EXIF has no
   timezone, so apply the regional offset yourself (+3 Bulgaria/Turkey summer, +2 most of the
   2021 Med).
5. **Phone export** — dense but it is the *phone*, not the boat. Match must be order-consistent:
   use Kendall's tau between position along the segment and matched time, not the match rate.
   Eight days of Galata Bay shuttling all score 100% on proximity alone.

Then check every leg's implied speed against roughly 0.4–9 kn before sending. This check has
caught real errors twice: a whole 194 nm crossing about to be uploaded for a 17 nm gap (44.6 kn),
and a leg whose start time was two hours wrong (8.2 kn).

## 5. Merge, then delete, then upload — in that order

The order is not stylistic. **A new fix within a few metres of an existing one is merged away
silently, with no error at all.** Two March 2025 legs and one 2025-08 leg were lost that way
before the rule was understood. So:

1. Decide what is superseded (`audit_duplicates.py`, `find_gaps.py`,
   `prune_superseded_fixes.py`), against the **precedence rule** at the top of this file.
2. **Export the doomed fixes to local GPX** — `reimport_journey.py --out nfl-retired --write`
   — and open the files to check they hold what you expect. Data comes off the site; it is
   not thrown away. A snapshot is not a substitute: it cannot be re-uploaded. This matters
   most for `NFL App` and hand-routed lines, whose points exist in no other local file.
3. **Harvest anything worth keeping from the fixes about to be deleted.** An old fix's own
   timestamp is often the best evidence for when a leg *arrived*, precisely because it came from
   a different source. Five March legs had their arrival times corrected this way, one by seven
   hours. Easy to skip, impossible to undo. Under the precedence rule this is also where a
   `Check in` earns its keep: **its time may be the only time there is**, even though its
   position is never usable.
4. Delete (`delete_fixes.py --token-file .nfl-token --ids ids.json`).
5. Upload.
6. Verify.

### Uploading

Import is by email, one GPX per message, from the address registered with the
noforeignland account — `[mail] from` in the configuration — to `[mail] to`, which defaults
to the importer's own `tracking@noforeignland.com`.

A laptop typically has no outbound mail, so the message goes via a host that does:

```
scp msg.eml MAILHOST:/tmp/
ssh MAILHOST '/usr/sbin/sendmail -f YOUR-REGISTERED-ADDRESS -t -oi < /tmp/msg.eml'
```

`-f` matters: it sets the envelope sender, so both the importer's address check and SPF see
the authorised address rather than whatever the relay would otherwise stamp on it. Getting
this wrong is silent — the message is accepted and never imported.
`boattracker.nfl.leg_export` builds the GPX and the MIME message.

Each GPX becomes **one fix**, timestamped at its **last** point. Splitting a passage into
per-day legs is therefore the only way to get per-day timestamps — and conversely, a five-point
chain spanning three days collapses onto one fix and throws the intermediate days away, which is
how 2025-08-05 ended up with no fix at all.

The **`creator` attribute drives the displayed source label**. Anything that is not plotter
geometry must say so there, or coarse hand-built or tracker geometry gets badged as a Raymarine
export. Note the cost, which is irreversible: re-uploading anything by GPX loses its original
`NFL App` / `Check in` / `Manual` label permanently — everything imported comes back as
`GPX Export`.

### Changing an existing line: use the API, not email

**Email costs the site owner money.** He pays his provider per volume for inbound mail, and
this project is a heavy sender — 106 tracker legs plus the 2021 return in two days. So mail is
now the last resort, not the default.

For any change to a line that is **already on the journey**, there is no need to send anything:

```
python3 boattracker.nfl.put_fix_path --fix-id <id> --path corrected.json --dry-run
python3 boattracker.nfl.put_fix_path --fix-id <id> --path corrected.json
```

`PUT /api/v1/boat/fix/path`, multipart, two fields — `fixId` and `path`, a JSON array of
`{lat, lon}`. It is the call the web map itself makes when points are dragged, captured from
the browser on 2026-08-05. Authorised by the same token `nfl_auth.py` handles.

This also **replaces the delete-and-re-upload dance** for route corrections: the fix keeps its
id, its timestamp and its source label, and only the geometry changes.

Three things to know before using it:

* **It replaces the entire path.** Not append, not patch. Two points and a seventy-vertex leg
  becomes a straight line, with no error and no undo. `put_fix_path.py` therefore fetches and
  saves the current path to `nfl-export/fixpath-before-<id>-<stamp>.json` before writing, and
  refuses paths under two points, coordinates off the planet, and `0,0`.
* **The stored path and the rendered line differ by one vertex.** The rendered line repeats
  its first point — the leading connector, an artefact of drawing order — while the stored
  path holds it once. Feeding a rendered path back unchanged grows one duplicate per round
  trip, so exact consecutive repeats are collapsed.
### A whole new leg, without sending anything

Creating a fix from a GPX needs email. Creating the *same result* does not — post the arrival
position, then write the line onto it:

```
python3 boattracker.nfl.add_fixes    --plan plan.json          # the fix: position + timestamp
python3 boattracker.nfl.put_fix_path --fix-id <new id> --path line.json    # its geometry
```

Two API calls, no mail. Verified 2026-08-06 on the 2021-06-08 Kadettangen → Torvøya leg: a
`Manual` fix at the anchorage, then 14 points of line attached to it. `Manual` fixes take
paths exactly as `GPX Export` ones do — the owner's own hand-drawn routes on the 06-02, 06-03
and 06-05 Manual fixes are the same mechanism.

Two differences from a GPX import, neither of them usually a problem:

* the source label reads `Manual` rather than `GPX Export`, so `prune_superseded_fixes.py`
  will remove it once real track covers it in time and position — which is the intended
  lifecycle, not a defect;
* the fix position and the line's last point are set separately, so **make the line end where
  the fix is**, or the leg will appear to stop short of its own arrival.

Email is now needed only when a GPX's own timestamps must drive the import.

## 6. Verify — read the mailbox, not just the API

The importer **replies by email**, with both success confirmations and errors. That is the
fastest and clearest check, and it went unused for a long time to real cost: the two failure
modes look identical in the API.

| Failure | Behaviour |
|---|---|
| New fix within metres of an existing one | absorbed **silently**, no error |
| Track timestamp matching one already present | **refused**, with a message naming the problem |

Only the first is invisible in the journey API. The second cost a diagnostic round trip that one
glance at the mailbox would have answered: five of twenty-two runs had been given the same
timestamp as their parent fix.

Then diff the journey against what was sent, and re-scan with `find_gaps.py`.

## 7. Remove duplication

Duplicated track is read as "sailed A to B, teleported back to A, sailed A to B again". It
zig-zags the map and **inflates the nautical-mile statistic**, so it is a data error, not a
cosmetic one.

```
python3 boattracker.nfl.prune_superseded_fixes --snapshot <snapshot>     # hand-placed, now covered
python3 boattracker.nfl.dedupe_tracker_lines --snapshot <s> --baseline <b>
python3 boattracker.nfl.rebuild_overlapping_fixes --snapshot <snapshot>
```

Rules that took several attempts to get right:

* A line is rarely duplicated end to end. **Rebuild** rather than delete: classify each edge,
  re-upload the surviving runs with their own timestamps, then delete the parent. Deleting
  outright trades one kind of data loss for another.
* Resolve overlap in favour of exactly one holder, or both sides get deleted and the water
  vanishes. Real track sources beat hand-placed ones; among hand-placed, earliest wins.
* Delete a hand-placed fix only when track data covers it **in time as well as position**. One
  `NFL App` fix at Port Varna sits 1 m from track recorded 18 143 hours later — a different
  visit entirely.
* Not every backtrack is duplication. Every rendered line begins with the *previous* fix's
  position, so a line whose track starts far away draws a long false first edge. That connector
  is an artefact of drawing order; strip it before measuring anything, or missing track measures
  as covered. And where the plotter genuinely was off — the 42 nm between Track 20 and 21 — the
  straight line is honest interpolation and must stay.

## 8. Commit

Everything except the raw tracks, which are gitignored. Use `git-ai-commit`; it encodes the
commit policy. Record what was *not* done and why, not only what was.

---

## Scripts

| | |
|---|---|
| `nfl_auth.py` | token: capture, store, check |
| `import_sdcard.py` | GUID-level dedup of a fresh card export |
| `track_dates.py` | date range per track and per segment, from export filenames |
| `find_gaps.py` | four gap-finding modes; `partial` is the one to trust |
| `leg_export.py` | shared GPX + MIME builder |
| `export_partial_runs.py` | fill a within-segment gap, dated from journey vertices |
| `exif_index.py` | photograph timestamp/GPS index, `--missing` for gaps in it |
| `audit_duplicates.py` | point-to-segment duplicate check with a time window |
| `delete_fixes.py` | bulk deletion by fixId |
| `prune_superseded_fixes.py` | drop hand-placed fixes that track data now covers |
| `dedupe_tracker_lines.py` | rebuild part-duplicated tracker lines |
| `rebuild_overlapping_fixes.py` | same for hand-placed lines |

The per-period exporters (`export_july2026.py`, `export_march2025_gaps.py`,
`export_aug31_varna.py`, `export_2023_gaps.py`, `export_2024_gaps.py`, …) are kept as the record
of what was sent and how it was dated. Their leg tables are the valuable part; read the nearest
analogue before writing a new one.
