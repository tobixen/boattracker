# Sources of date, time and position

Every source that can put the boat at a place at a time. The Raymarine chartplotter records
position without time, so almost all the work in this project is joining these two halves
back together; this is the inventory of what is available to join with.

Kept separate from `RAYMARINE-GPX.md` (which is about the plotter format) because the
question "what evidence exists for this day?" keeps coming up and the answer was scattered.

## The precedence rule — the owner's, 2026-08-12

**The record on noforeignland should be as complete as possible: every available source
considered and merged, the most reliable kept, the less reliable not used there.** The two
halves of "reliable" come from different sources, and that is the whole point of the rule:

| | Best source | Why |
|---|---|---|
| **Position** | **Raymarine chartplotter** | a real marine GPS logging densely; carries no time at all |
| **Time** | **the on-board GPS/GSM tracker** (`GPX Export`) | every fix is stamped by the GPS clock as it is recorded |

**Where both exist, almost everything else can be set aside** — after a quick QA that the two
data sets actually agree. Where the plotter has geometry but no time, the tracker's or the
site's own timestamps are what date it.

Then, source by source:

| Source | Position | Time | What to do |
|---|---|---|---|
| `Raymarine GPX Export` | **best** | none | keep; date it from the tracker or from journey data |
| `GPX Export` (tracker) | good, coarse | **best** | keep; it is the clock everything else is set by |
| `Check in` | **never accurate** | not trustworthy | remove from the site wherever better data exists; its time may still be used when there is nothing better |
| `Manual` | usually exact | usually exact | **depends on where it sits** — a one-point fix *in the middle of* a track must go, one *between* two tracks should stay. See below |
| `NFL App` | good | good | **generally quite reliable, just less so than the other two** — but see the coverage problem below. Replace with plotter+tracker track where that exists |

**The `NFL App`'s weakness is coverage, not precision.** The owner's clarification,
2026-08-12, and it is the thing to watch for. The app is not reliably started when the boat
leaves nor stopped when she arrives, so:

* **a passage is often only partly recorded** — the line begins late, ends early, or both,
  which is why an app line can look like a fragment of a leg the plotter holds in full;
* **it sometimes keeps running ashore**, and then draws a car, train or walk as though it
  were a passage. That collides directly with this project's first rule — *only sea voyages
  belong on the journey* — so an app line has to be checked for **what it covers** before it
  is trusted, not merely for how accurate it is.

So the reason to prefer plotter and tracker over the app is completeness and boundaries
rather than metres. And app lines have one specific use before they go: **they carry
timestamps, so they can date Raymarine geometry covering the same water** where nothing
else can.

### A `Manual` one-point fix: one kind must go, the other should stay

Both carry `source: Manual` and look identical in every listing, but they do opposite jobs,
so the precedence rule cannot rank `Manual` with a single verdict:

* **In the middle of a track — must be deleted.** A fix is one timestamp for a whole line,
  and the renderer draws fix to fix, so a lone point inside a leg makes the map run to it and
  back out again: a **manufactured backtrack**. The 2022-07 Polish coast is the worked
  example — bare fixes added there laid straight 2-vertex chords across real track and were
  deleted again (`NFL-CHAPTERS.md`).
* **At a harbour or anchorage between two tracks — should be kept.** It competes with no
  line, and it carries something the data model otherwise cannot express: **a departure
  time.** Every fix timestamp is an *arrival*, so without such a fix there is no way to say
  when the boat left.

`IMPROVE-TRACKS.md` has the full statement of what a fix is, the leg rule that decides how
long one should be (**one fix, one leg, from one significant stop to the next**), and the
order for building one (**manual fix first, then the track data**).

### Nothing is thrown away — it stops being used *on the site*

The owner's correction, the same day, and it is a rule about two different places. "Set
aside" and "delete" above always mean **removed from noforeignland**, never destroyed. A fix
that comes off the site must first exist locally as something that could be put back:

* a **snapshot** (`nfl-snapshots/`) preserves it, but a 2.4 MB JSON blob is not something you
  can re-upload;
* `boattracker.nfl.reimport_journey` turns the rendered geometry into **GPX**, which is;
* so the order is **export locally, verify the export, then delete** — and for `NFL App`
  lines the owner asked for this explicitly, because their geometry exists nowhere else.

This matters most for exactly the fixes the precedence rule condemns. A `Check in` has a bad
position, but it is still evidence that the owner was somewhere on that day, and a hand-routed
`NFL App` line may hold corrections made on the map that no local file has ever seen — see
"Hand-placed map corrections exist only on noforeignland" below.

## Position without time

| Source | Period | Coverage | Precision |
|---|---|---|---|
| `Tracks202607.gpx` | 2025-08 .. 2026-07 | tracks 46–60 plus `57.202509` | dense, 0.4–12 m point spacing |
| `TracksA.gpx` | 2026-07-27 .. 07-28 | tracks 61–62 | dense; Track 62 uncapped, i.e. still live |
| `Tracks.gpx` | 2026-07-29 .. 08-12 | tracks 63–67W | dense; **484 points are in Peru** — see below |
| `TracksAdvt.gpx` | 2025-07 .. 2025-08 | tracks 34–45 | dense |
| `TracksCfn.gpx` | 2025-04 .. 2025-07 | tracks 30–41 | dense |
| `TracksQ.gpx` | 2024, 2025-02 .. 03 | `ToSantorini2024`, tracks 7–20 | `ToSantorini2024` is **coarse**, 461–473 m spacing |
| `TracksC.gpx` | 2025-03 | tracks 21–26P | dense |
| the `*.gpx` crops | 2023 .. 2024 | `Track 1`, `Med 2023`, `Track 3`, `Track 4`, `Track 7` | **coarse**, 400–1100 m spacing |

The crops are `benelux.gpx`, `france-etc.gpx`, `germany1.gpx`, `Poland1.gpx`,
`lisbon2.gpx`, `lisbon3.gpx`, `to-lisbon.gpx`, `raymarine_rest.gpx`, `tmp.gpx`.

**The plotter sometimes records Peru.** The diary, 2026-08-07: *"the navigator several
times dropped GPS, and then later decided we were in Peru, cruising in a circle in 109
knots."* In `Tracks.gpx` that is **484 points across 11 entire segments** of Tracks 64Xxx
and 65, all at −12.04, −77.05, never mixed into a good segment. Three things about it:

* **It passes every obvious sanity check.** The coordinates are valid, the segments are
  well-formed, and the points are dense and smooth. Only the *position* is absurd.
* **No earlier export carries it and nothing reached the journey** — checked across all
  six `Tracks*.gpx` and every journey vertex, 2026-08-15.
* **The guard has to be point-weighted, not per segment.** `Track 65` holds seven Peru
  segments against four real ones, so a median over segment centroids lands in Peru and
  throws the real track away. Over points it is 335 against 9650.
  `timestamp_segments.drop_off_planet()` and `find_gaps.drop_off_planet()` both do this;
  without the second, a scan reports 40.5 nm of Peru as missing track for ever.

**`france.gpx` was redundant and has been deleted** (2026-08-03). Its segments 0-20 were
byte-identical to `france-etc.gpx`, its seg 21 was the same segment *truncated* — 773 points
and 251.5 nm against 817 and 268.7 — and `france-etc.gpx` holds 32 further segments it
lacked, the whole Iberian run. An export built on it would have stopped 17 nm short in the
Bay of Biscay. Kept in this list because **backup copies elsewhere carry the same defect**:
if one turns up, it is not a second source, it is a shorter copy of `france-etc.gpx`.

**Truncated at EOF.** `benelux.gpx` ends without its closing `</trkseg></trk></gpx>`, and
the deleted `france.gpx` did too — what a crop script that never wrote its tail leaves
behind. Consequences worth knowing:

* An XML parser will not read them at all. `leg_export.segment()` splits on the **opening**
  `<trkseg>`, so it does, and its indices are stable either way.
* Matching `<trkseg>.*?</trkseg>` instead makes the final segment **silently vanish**. In
  `benelux.gpx` that is seg 8, Zeebrugge to Calais. Both files happen to have the unclosed
  segment last, so nothing was shifted — had it been in the middle, every later index would
  have pointed at the wrong water with nothing raising.

Repairing the files is optional now that the reader copes, and would not change any result.

**None of the crops carry timestamps**, which is the whole reason for the 2022 re-dating
work: the importer stamped each upload with one time of its own, and those times are
guesswork. Where a crop and a photograph disagree, the photograph wins — see the export log
for two aggregate timestamps that geotagged photographs proved impossible.

## Time with position

Ranked by how much weight to give them.

| Source | Period | Strength | Weakness |
|---|---|---|---|
| **Engine log** (in the diary) | 2025 .. 2026 | explicit UTC, hours and total miles; the strongest evidence there is | sparse — a handful of entries per month |
| **Raw tracker feed** (`gpstracker-archive/`) | 2021-05-01, 2021-06-15 .. 10-12 | the same GSM/GPS tracker, but its **server log** rather than what noforeignland kept: 504 188 fixes across 103 days, one every ~17 s, denser than the chartplotter. UTC, and it carries the tracker's **own reported speed** | extended 2026-08-09 from a second location (see the row below), which added 2021-08-22 .. 10-12 and 2021-05-01; three breaks totalling 38.2 nm were crossed out of contact (`boattracker.nfl.tracker_archive --gaps`); it places the *tracker*, which lived aboard but is not by itself proof the boat moved |
| **Raw tracker feed, NOT yet fetched** (`/var/www/html/solveig.oslo.no/gpstracker.raw*` on `srv1.tobixen.no`) | ~~2021-08-22 .. 10-12~~ (fetched), 2023-06 .. 08, 2023-12, **all of 2024**, 2025-01 .. 02 | the same log, in a second location nobody had looked in. `gpstracker.raw.2024` alone is 225 MB and holds **~2.3 million fixes across every month of 2024**, 225k–257k a month. Same TK103 wire format, so `tracker_archive.py` reads it unchanged | discovered 2026-08-09 and untouched. Date ranges above are read from the `BR00YYMMDD` field inside each file, not from mtimes, which disagree |
| **noforeignland journey API** | 2021-06 .. 2025-02 | real GPS/GSM tracker feed; **per-vertex timestamps** (`[lon, lat, epoch_ms]`) | coarser than the plotter; stops outside cellphone coverage, so offshore stretches are straight chords. Many 2023 vertices carry **epoch 0** — no time at all |
| **Organic Maps phone export** | 2025-07-30 .. 2026-08-14 | dense, 269 594 fixes | the phone, not the boat: includes flights, land travel, and time ashore. Match must be order-consistent, not just near. Read it with `boattracker.nfl.omaps_export` |
| **Geotagged photographs** | scattered | exact to the second, and unambiguous where the place is unique | only where photos were taken and kept EXIF, and **the position can be flatly wrong** — see below. Index: `~/s/photos.tobixen/exif-index.json`, the whole corpus (44 565 files), built by `boattracker.nfl.exif_index` |
| **Diary stop lines** (`arrived at anchorage 36.8028,28.2358 (Icmeler)`) | wherever the tracker ran | **position *and* UTC timestamp in one line**, machine-written by the old tracker's own stop detection — the best evidence there is for when and where a leg ended, better than any hand-placed guess | only exist where the tracker was recording; a few carry the diary's own caveat (2024-04-06 says "time is uncertain, tracker hasn't been giving much data recently") and those lose to the tracker's vertices. **The 2026 blocks are not tracker output** — see below |
| **Diary clock times** | 2023-06 .. 2026-08 | often gives departure and arrival | prose, needs reading. **The times in the prose are local, UTC+3** — the owner's ruling, 2026-08-15. Only an entry that says `UTC` is UTC, and the engine log always does. An earlier note here called the timezone "inconsistent"; it is not, it just has to be converted |
| **Diary headings** | 2023-06 .. 2026-07 | an ordered place chain per day; fixes the date and the leg count before any track is looked at. **This is where significant stops are recorded**, and therefore where the leg boundaries come from — see `IMPROVE-TRACKS.md` | place *names*, not coordinates; `journey/PLACES.md` maps the ones that have been asked about |
| **noforeignland journey API** | 2025-04 .. 2025-09 | — | **poor**: 50 hand-placed `Manual` / `Check in` points. Do not use as a reference fix |
| **boattracker JSON/GPX** | 2023-12-30 .. 2024-01-01 | good | a single 3-day anchoring episode at Dubrovnik |

### The 2026 `### Time and positions` blocks are reconstructed, not recorded

**Written 2026-08-15, and this is a trap by construction.** The 2021–2025 blocks in the
diaries were emitted by the old tracker's own stop detection from real GPS fixes. The
tracker has not run since, so fourteen blocks covering **2026-07-26 and 07-29 .. 08-12**
were written by hand into `diary-2026.md` in the same format, from the plotter track and
the phone. They look identical in every respect, down to the `YYYY-MM-DDTHHMMSS UTC`
stamps.

Each one therefore carries an italic provenance line naming which it is, and there are two
kinds:

* **matched against the phone** — 07-26, 08-06 (the Kaliakra passage), 08-07, 08-09, 08-10,
  08-11, 08-12. Seconds are meaningful; the positions are the plotter's.
* **pinned from the diary and the engine log** — 07-29 .. 08-05 and the 08-06 morning leg.
  The phone was not recording. **The times are approximate to within the half hour and their
  seconds are padding**; the positions are still the plotter's and are good. The round
  numbers (`T134500`, `T090000`) are the tell.

So: read the italic line before using a 2026 timestamp for anything, and never feed one back
in as if it were an independent measurement — it is derived from the same plotter track it
would be used to date. `historic/export_aug2026.py` holds the derivation.

**Looking for more of the raw feed.** `find-tracker-logs.sh` searches a disk for it by the
tracker's own wire format — `BR00` + `YYMMDD` + the A/V flag — so it finds a log whatever it
has been named, and inside gz/bz2/xz/zst/zip as well. Two properties make an empty result
worth something: it proves its pattern against a known record before sweeping and aborts if
that fails, and it routes files over 200 MB through `tr` first, because the tracker writes a
whole day as one 460 kB line and grep buffers a line at a time. Take the year and the
mountpoint: `./find-tracker-logs.sh 2022 /mnt/olddisk`. Results so far are in `TODO.md`.

`journey/PLACES.md` holds ~40 place coordinates, in decimal and in degrees-decimal-minutes, flagged
for uniqueness and provenance. Uniquely-visited places are the most valuable dating evidence
of all: one segment passing within 11 m of the Ayvalık marina dated a whole day, because the
boat called there exactly once.

## Where more coordinates would actually help

Asked directly: should place coordinates be extracted from the diary headings?

**Not for the 2023–2024 chord repairs.** Those already have exact coordinates at both ends —
they come from the tracker's own vertices — and the plotter supplies the geometry between.
Place names add nothing there.

**Yes for the stretches with no plotter track at all.** These can only be improved by a
hand-built waypoint chain through named places, the way 2025-08-04..06 was bridged. That is
where a heading like "Kardirga Koyu - ..." needs to become a coordinate:

* **13 tracker chords, 219.6 nm, with no plotter cover** — mostly the Cretan coast in autumn
  2024, where the plotter appears not to have been recording.
* **22.62 nm on 2025-08-21**, Track 45 → 46, Foça towards Cumhuriyet.
* **8 small 2025-02/03 segments, 18.4 nm**, which need a *day* rather than a position:
  Track 8 s0, 8 s1, 9 s0, 9 s3, 13 s1, 23 s1, 23 s2, 25 s3.

## Photograph positions: three ways they go wrong

Written 2026-08-03, while two efforts were using the photograph index at once — 2021 track
building and the 2022 Polish coast re-dating. Both hit position errors, so the findings are
here rather than in either one's notes.

The index (`~/s/photos.tobixen/exif-index.json`) now holds **43 463 records, 28 957 with a
position**, and carries three fields beyond time and place: `fix` (`GPSProcessingMethod`),
`gps_time` (the fix's own clock) and `hpe` (positioning error in metres, where written).

**1. The position is true but is not the boat.** The photographer was ashore, on a train, or
a thousand miles away. This is the commonest case and the `ashore` flag in
`manual-locations.json` exists for it — the photograph is *not* wrong and must keep its own
position; the flag only says the position must not become boat track. 2021-05-16 is the
worked example: the pictures really are in Göteborg, the boat really was at Strömstad.

**2. The position is false.** The camera wrote a cached lock. `huawei/IMG_20220723_215745.jpg`
shows a Kiel canal lock and is tagged in the Gdansk basin, 900 nm away, where the phone last
had a real fix before going to sea. Its GPS clock was *contemporaneous*, so a staleness test
does not catch it. 383 records do have a `gps_time` whose date differs from the photograph's
date, and those are stale outright.

**3. Null island.** Exactly `0.0, 0.0` — **62 records**, now discarded at index time and
cleared from the existing index. Worth noting how nearly this was undercounted: a
spike test only found three of them, because it needs a same-day neighbour either side to
judge against. Counting them directly found the rest.

### `fix` does not tell you which of these you have

It bounds precision — `cellid` is 1-10 km, enough to name a harbour and useless as track
geometry — but it does not predict error. Measured across all 28 957 positions, counting
*spikes* (a photograph far from both temporal neighbours while those neighbours are close to
each other, which separates a bad fix from real travel):

| method | positions | spikes | rate |
|---|---|---|---|
| gps | 9 657 | 7 | 0.07% |
| network | 7 745 | 3 | 0.04% |
| cellid | 7 275 | 3 | 0.04% |
| unknown | 1 274 | 3 | 0.24% |

`gps` is marginally the **worst**. So do not filter on it. What works is the spike test above,
`photo_survey.py`'s 0.4-9.0 kn check, and looking at the picture — the Kiel lock was settled
by opening the file.

### Correcting a position

`manual-locations.json` entries are keyed by `path` or `day`. Prefer `path`: a day-level flag
on 2021-05-17 would have discarded that afternoon's passage south, because only the two
morning photographs were ashore.

| key | meaning |
|---|---|
| `ashore: true` | position is real, but it is the photographer, not the boat. EXIF untouched |
| `override: true` + `lat`/`lon` | the EXIF position is **false**; replace it. The original is kept as `exif_lat`/`exif_lon` so the correction stays auditable |
| `drop: true` | the EXIF position is false and no replacement is known |

Supplying `lat`/`lon` **without** `override` fills a missing position only; it will not
displace a measured one. That asymmetry is deliberate — recall must never quietly overwrite
measurement — and it is why `override` had to be added rather than inferred.

**And photographs are the cheapest untapped source — but only up to June 2023.** The full
sweep has now been run; the figures above replace the old 150-row scoped cache. A geotagged
photograph is exact to the second, which is better than anything except the engine log.

**Geotagging stops in June 2023 and never resumes that year**, measured 2026-08-15:

| month | photographs | with GPS |
|---|---|---|
| 2023-05 | 293 | 201 |
| 2023-06 | 391 | 72 |
| 2023-07 .. 12 | 1681 | **0** |

The cameras from September 2023 are `SM-T575` and `M2101K9G`, neither of which wrote GPS. So
an earlier note here — that sweeping the 2023–2024 directories would date several of the 13
uncovered chords outright — is **true for 2021 and 2022 and false for the 2023 delivery**.

What remains usable there is the **timestamp**, plus the owner's offer of 2026-08-15:
*"Some of the photographs without GPS coordinates can still be pinpointed by looking into
them, I can help with that."* That turns a photograph into a position by identification
rather than by EXIF, and `manual-locations.json` is where the answer goes. `TODO.md`, "The
2023 delivery", has the days worth asking about.

## Two rules that cost real data to learn

**Density is evidence.** A straight line made of many points is worth more than the same
line made of two: a two-point edge signals that data is missing, while a densely sampled
straight run is positive evidence the boat sailed straight. So plotter track is worth
uploading even where it barely changes the drawn shape — and 25 m of deviation can be the
difference between a line crossing land and not crossing it. Do not filter repairs by how
wrong the line looks.

**Hand-placed map corrections exist only on noforeignland.** Points added to a line in the
web map are in no local file. Before deleting any fix, snapshot it and compare its rendered
vertex count against the GPX that was uploaded — the 2025-08 gap-fill chain was sent with 5
points and rendered 16, and that difference was the owner's own work routing the line off
the land.
