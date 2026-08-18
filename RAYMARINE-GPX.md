# Raymarine GPX track exports

Notes on the GPX files exported from the boat's Raymarine chartplotter, kept here
because the [Chinese GPS tracker](README.md) that normally feeds this project is
down — the Raymarine exports are what we use to fill the resulting gaps in the
boat tracks (see `crop_raymarine_track_to_gap.py`).

## The one thing that matters most: there are no timestamps

The exports contain **no `<time>` elements at all** — not on track points, not on
tracks, not in metadata. Verified: zero occurrences across every export.

Consequence for gap filling: a Raymarine track gives you *geometry and depth, but
not when the boat was there*. You cannot merge it into a time series directly.
This is why `find_gap()` / `split_to_point()` in `crop_raymarine_track_to_gap.py`
match on **position** (`jump_from` / `jump_to` coordinates plus a distance
tolerance) rather than on time, and why timestamps for injected points have to be
interpolated from the boundaries of the gap being filled.

There is also no `<ele>`, no `<wpt>`, and no `<rte>` — tracks only.

## File structure

```xml
<?xml version="1.0" encoding="UTF-8"?>
<gpx xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" version="1.1"
     xmlns="http://www.topografix.com/GPX/1/1" creator="Raymarine"
     xmlns:raymarine="http://www.raymarine.com"
     xsi:schemaLocation="http://www.topografix.com/GPX/1/1 http://www.topografix.com/GPX/1/1/gpx.xsd
                         http://www.raymarine.com http://www.raymarine.com/gpx_schema/RaymarineGPXExtensions.xsd">
 <trk>
  <name>Track 46</name>
  <extensions>
   <raymarine:TrackExtension>
    <raymarine:Colour>Black</raymarine:Colour>
    <raymarine:GUID>bd80-5323-01d6-fec9</raymarine:GUID>
   </raymarine:TrackExtension>
  </extensions>
  <trkseg>
   <trkpt lon="26.75720198079944" lat="39.16756782256081">
    <extensions>
     <raymarine:TrackPointExtension>
      <raymarine:WaterDepth>15.03</raymarine:WaterDepth>
     </raymarine:TrackPointExtension>
    </extensions>
   </trkpt>
   <trkpt lon="26.7571" lat="39.1676"/>          <!-- no sounding: self-closing -->
  </trkseg>
  <trkseg>...</trkseg>                            <!-- recording gap starts a new trkseg -->
 </trk>
 <trk>...</trk>
</gpx>
```

Indentation is one space per nesting level, LF line endings, one `<trkpt>` child
element per line.

### Sampling interval, and when it can tell you about speed

The plotter has settings for how often to lay a track point and whether to trigger on
distance, on time, or both. "Distance and time" was the default for a long time; the
setting is changed rarely, so it holds across long runs of tracks and the changes show
up as steps in point spacing. Measured across the corpus in GUID order:

| Tracks | Median gap | Gaps under 1 m | Reading |
|---|---|---|---|
| ToSantorini2024, Track 7 | 461–473 m | 3 % | very coarse — one point every few hundred metres |
| Track 8 .. 19 | 1.4–4.7 m | 1–43 % | frequency increased sharply at Track 8 (Feb 2025) |
| Track 20 .. 26P | 6.9–12.4 m | 0–36 % | wound back down again from Track 20 (2025-03-09) |
| Track 46 .. 54 | 4.9–12.5 m | 0–8 % | as above |
| Track 55 .. 60 | 0.4–8.8 m | 15–57 % | frequent time sampling |

**The useful diagnostic is the share of gaps under a metre, not the median.** Under
pure distance triggering a stationary boat lays down no points at all, so near-zero
gaps cannot occur; a large share of them proves time triggering was active and caught
the boat sitting still. Where that share is high — Track 55 at 57 %, Track 57 at 50 %,
Track 23 at 36 % — dense points really do mean slow going, and speed can be read off
the spacing. Where it is near zero — Tracks 24, 25, 48, 49, 53, 54 — spacing is
constant regardless of speed and says nothing.

Getting this backwards caused a real error. 952 points covering 1.71 nm at the start
of `Track 10 s0` were read as a passage, when Track 10 has only 1.8 % of gaps under a
metre — so those points are a boat swinging at anchor for a day and a half at Kara
Ada, laying down points on distance as it swung. Reading them as movement pushed a
departure a day early and misdated two uploads. See `journey/DIARY-DISCREPANCIES.md`.

### The measured intervals, and what they let you deduce

Estimated from stationary stretches whose duration is bracketed by trusted fixes:

| Config | Time step | Measured from |
|---|---|---|
| Tracks 8–19 (from 2025-02) | ~103 s | Track 8 s3 + Track 9 s0, 1819 points over 52.1 h at Çeşme, 37 % of gaps under 1 m |
| Tracks 55–60 (Sept 2025 on) | ~48 s | Track 55 s2, 5149 points over 69.1 h at Varna Lake, 83 % under 1 m — the firmer of the two |

The Feb figure is closer to an upper bound, since only 37 % of its gaps are time
triggered and the rest inflate the average.

Combining the time step with the distance step gives the speed at which the distance
trigger takes over:

| Config | Distance step | Time step | Distance trigger wins above |
|---|---|---|---|
| Tracks 8–19 | ~4 m | ~103 s | 0.08 kn |
| Tracks 20–54 | ~12 m | ~103 s | 0.23 kn |
| Tracks 55–60 | ~12 m | ~48 s | 0.49 kn |

So under way — anything over about half a knot — the distance trigger is what fires,
and **point count measures distance travelled, not time elapsed**. Speed cannot be
read off point density while sailing, in any of the configs.

What it does give you is the reverse, and it is worth having: a run of consecutive
near-zero gaps must be time triggered, so **counting those points and multiplying by
the time step gives the duration of that stop**. That is the missing tool for
allocating time inside a segment that mixes a stop with a passage — the case that
caused the Kara Ada error. It works on tracks with a high near-zero share (55, 57,
23, 58, 60) and not on those without (10, 11, 24, 25, 48, 49, 53, 54), where a
stationary boat that is swinging still covers distance and triggers on distance.

The wider lesson for dating: **cumulative distance is not a proxy for elapsed time**
across any span that contains a stop. Interpolating times along distance between two
reference fixes silently compresses the stop and stretches the passage. It is only safe when
the span is known to be continuous movement, which is why reference fixes either side of a
single passage give good times, and reference fixes a day apart do not.

### Gotchas for parsers

* **`lon` comes before `lat`** in the `trkpt` attributes — the opposite order from
  most GPX writers. Anything that assumes `lat` first, or that parses the two
  attributes with one positional regex, will silently swap the coordinates.
  (`parse_trkpt()` in `crop_raymarine_track_to_gap.py` searches for each attribute
  separately, so it is safe.)
* **`<trkpt>` may be self-closing** when no sounding was recorded for that point.
  ~8% of points in the current corpus. Code that assumes every `trkpt` has an
  `</trkpt>` closing tag or an `<extensions>` child will break.
* **Coordinates carry absurd precision** — 14 to 19 decimal places, i.e. down to
  nanometres. Real accuracy is metres. Do not use string equality on coordinates
  as a general identity test across *different* export generations; within one
  plotter's exports it happens to be stable and exact, which is what makes
  set-based deduplication work here (see below).
* **A track can contain many `<trkseg>` elements** — up to 130 in one track. Each
  new segment is a break in recording (plotter switched off, usually overnight or
  between legs). Don't assume one segment per track.
* Regexes like `WaterDepth>([^<]+)<` also match the *closing* tag and capture the
  following whitespace. Match on `<raymarine:WaterDepth>([^<]+)</`.

## Tracks, numbering and ordering

The plotter names tracks `Track N` with a running counter, and caps a track at
**10 000 points**; when the cap is hit it closes the track and opens the next one.
So a single voyage is spread over several consecutive `Track N` files with no
logical boundary between them — the split is purely mechanical.

**A track can span an arbitrarily long gap.** `Track 57.202509` holds September
2025 in segments 0–6 and then July 2026 in segments 9–11: the plotter was switched
off for the nine-month haul-out and simply carried on appending to the same track
at launch. Track numbers therefore order in time, but a single track is *not* a
single period, and a track's name is no guide either. The only safe reading is that
segment order within a track is chronological.

The user occasionally renames a track (`Med 2023`, `ToSantorini2024`,
`Track 26P`, `Track 57.202509`), so names are not reliably parseable.

`raymarine:GUID` has the form `bd80-5323-XXXX-YYYY`:

* `bd80-5323` is constant across every export — it identifies the plotter.
* The **third group increases monotonically with track creation order**. Verified
  against all 41 tracks in the corpus: sorting by the third group reproduces the
  `Track N` numbering exactly.

That third group is therefore the only chronological ordering key available in
these files, given the absence of timestamps. It orders tracks relative to each
other; it does not tell you absolute dates.

Gaps in the counter mean those tracks were never exported. Tracks 27–45 were missing
for a while and were recovered from the plotter's SD card in July 2026 — see
`boattracker.nfl.import_sdcard`.

### The GUID step is NOT a missing-track detector

The third GUID group increases monotonically but **not uniformly** — the step between
consecutively numbered tracks is usually about 6, but 12 or 13 occurs perfectly
normally. Track 41 → 42, Track 20 → 21 and Track 60 → 61 all step 12–13 while being
consecutively *named*, so nothing is missing at any of them. An earlier version of
this document claimed a track was permanently lost between 41 and 42 on the strength
of the GUID step; that was wrong.

Use the **track names** instead. They carry the plotter's own running counter, so a
missing number is a missing track. On that test the corpus holds Track 1, 3, 4, 7 and
then every number from 7 to 62 — with `Med 2023` and `ToSantorini2024` being renamed
tracks, presumably 2 and one of 5/6. So at most one early track is genuinely absent.

### Recording gaps: check contiguity instead

What the GUID step was mistaken for is a **recording gap** — the plotter switched off
between two tracks. The test is whether the last point of track N and the first point
of track N+1 coincide. 54 of the 60 boundaries in the corpus are contiguous to within
300 m; six are not:

| Boundary | Unrecorded |
|---|---|
| Track 3 → Track 4 | 7.00 nm |
| ToSantorini2024 → Track 7 | 96.11 nm |
| Track 20 → Track 21 | 42.09 nm |
| Track 41 → Track 42 | 43.54 nm |
| Track 45 → Track 46 | 22.62 nm |
| Track 60 → Track 61 | 37.69 nm |

249 nm in total. The Track 41 → 42 gap is the one that matters for dating: it covers
the stretch containing Kumkale and Yeniköy limani, which is why the 2025-08-05
photograph taken at Yeniköy has no track to sit on. That water was sailed, it was
simply not recorded, so nothing can recover it.

**Two different causes.** Most of these are the plotter being switched off, but
Track 60 → 61 is not: Tracks 58, 59 and 60 all end at 9981, 9985 and 9987 points, i.e.
at the ~10,000-point cap. Track 60 filled up in mid-passage on 2026-07-23, two hours out
of Varna, and recording stopped there rather than rolling over into a new track — the
plotter was restarted by hand at the Sozopol anchorage, which is where Track 61 begins.

So a full track is itself a warning: whenever a track's point count is within a few
dozen of 10,000, check the boundary, because the gap that follows is at a position the
boat was *under way* rather than at a berth. Gaps from a switched-off plotter almost
always start where the boat had stopped.

## Point extensions

| Element | Points | Notes |
|---|---|---|
| `raymarine:WaterDepth` | 328 730 | Metres, 2 decimals, depth below transducer. `0.00` means no bottom lock, not zero depth — treat as missing (581 occurrences). Observed range 0.5–216.8 m. |
| `raymarine:WaterTemp` | 8 523 | **Do not trust.** Kelvin, but the values run 325.6–333.2 K = 52–60 °C, which is impossible for sea water, and they pin at exactly 333.15 K (60.00 °C). Faulty or misplaced sensor. Only present in the two newest exports. |

A point may carry depth, temperature, both (4 561 points), or neither.
`raymarine:Colour` on the track is `Black` or `Blue` and carries no meaning beyond
display.

The depth soundings are the genuinely valuable part of these files beyond the
track geometry — 328 730 soundings along the sailed routes.

## Current corpus

Exports live in this directory, untracked by git (only `test_raymarine.gpx` is
tracked, as a test fixture). They are large; do not `git add -A` here.

| File | Points | Tracks | Coverage |
|---|---|---|---|
| `Tracks202607.gpx` | 147 784 | 46–60, and `57.202509` | N Aegean → Marmara → Bulgarian Black Sea coast (lat 39.17–43.25, lon 25.80–29.12) |
| `TracksA.gpx` | 15 161 | 61–62 | the 2026-07-27 Sozopol → Varna return and the 07-28 Chaika day. Exported 2026-07-29; Track 62 is uncapped at 5166 points, i.e. still the live track |
| `Tracks.gpx` | 61 962 | 61–62, 63–67W | exported 2026-08-13; 46 301 points are new (63, 64Xxx, 65, 66, 67W). The 2026-07-29 → 08-12 Varna locals, the Constanța return trip and the lay-up. **484 of its points are in Peru** — see below |
| `TracksQ.gpx` | 141 595 | ToSantorini2024, 7–20 | Aegean, Greece, Turkey (lat 35.34–44.20, lon 23.25–29.13) |
| `TracksC.gpx` | 53 005 | 21–26P | Marmara, Bosphorus, W Black Sea (lat 40.42–43.19, lon 27.03–29.12) |
| the `*.gpx` crops | 31 220 | 1, Med 2023, 3, 4 | Portugal → Baltic delivery, cropped into `benelux.gpx`, `lisbon2.gpx`, `lisbon3.gpx`, `france.gpx`, `france-etc.gpx`, `germany1.gpx`, `Poland1.gpx`, `to-lisbon.gpx`, `raymarine_rest.gpx`, `tmp.gpx` |

The three large `Tracks*.gpx` files and the crop set are mutually disjoint — pairwise
shared point count is zero. Total: **373 326 unique points**, plus `TracksA.gpx` and the
46 301 new points in `Tracks.gpx`. `import_sdcard.py` deduplicates by `raymarine:GUID`,
which is stable across exports; run it rather than comparing file sizes.

### The plotter records Peru

The diary, 2026-08-07: *"the navigator several times dropped GPS, and then later decided
we were in Peru, cruising in a circle in 109 knots."* This is the first export in which it
survived to the file: **484 points, 11 whole segments** of Tracks 64Xxx and 65, every one
at −12.04, −77.05, none mixed into a good segment.

Why it is easy to miss and hard to filter:

* The coordinates are **valid** and the segments well-formed and densely sampled, so a
  range check passes them. Only the position is absurd.
* `Track 65` holds **seven** Peru segments against four real ones, so a rule that takes a
  median over segment *centroids* elects Peru and discards the real track. Weight by
  points and it is 335 against 9650. `find_gaps.drop_off_planet()` and
  `timestamp_segments.drop_off_planet()` both do it that way.
* Judge **within a track**, not across the corpus: the corpus spans Norway to Turkey, so
  a corpus-wide distance rule would drop real segments. Peru is ~6550 nm from the Black
  Sea, so the threshold has plenty of room.

No earlier export contains such points and none had reached the journey; both were checked
on 2026-08-15.

### A stop can be found in an export that carries no time — but not timed

**2026-08-15.** The technique is the one in "Sampling interval" above, run backwards, and it
is the only way to find a stop when neither the tracker nor the phone was recording. A boat
sitting still keeps triggering on *time*, so the stop survives into the export as a **dense
cluster of sub-metre gaps** even though every timestamp is missing.

The worked example is the Varna Port border-police berth on 2026-08-10. The phone had stopped
9.5 nm earlier, so nothing timed covered it. `Track 67W` s2 leaves **535 points inside a 150 m
circle with 232 m of track run**, and **94 % of the gaps in that cluster are under a metre** —
the boat was genuinely stationary, not merely slow. The centre is 43.192821, 27.920894, which
the owner confirmed as *exactly* the border police berth, 320 m north of the G G Yacht Club.
Both it and a second Port of Varna waiting berth he gave are now in `journey/PLACES.md`.

Two things about running the test:

* **Scan the raw geometry, not a timestamped export.** Once times have been interpolated along
  distance the speed is constant by construction and the dwell is erased. Run it on
  `Tracks*.gpx` directly.
* **Ask "how many consecutive points stay inside radius R", not "where is the track slowest".**
  A slowest-window search over the same leg returned six candidates, all of them out at sea,
  and missed this berth entirely.

**The duration does not follow, and trying to take it cost an hour here.** "Sampling interval"
above gives the rule — near-zero points × the time step — but the step is only *measured* for
Tracks 8–19 (~103 s) and 55–60 (~48 s). Applying 48 s to this cluster gives 504 × 48 s =
**6.7 hours**, which the day flatly cannot fit: the morning ran at a measured 2.41 kn and the
boat was back at Chaika before dark. So the step for Tracks 63–67W is much shorter and has
never been measured. Inverting the owner's own half hour gives **≈3.6 s per point** — a
hypothesis worth testing the first time a stay of known duration turns up in these tracks.

The share of sub-metre gaps for the 2026 tracks, which is what decides whether the test can
work at all:

| Track | Median gap | Gaps under 1 m |
|---|---|---|
| Track 61 | 10.2 m | 1.1 % |
| Track 62 | 1.0 m | **50.1 %** |
| Track 63 | 8.0 m | 15.9 % |
| Track 64Xxx | 11.0 m | 12.0 % |
| Track 65 | 12.1 m | 0.1 % |
| Track 66 | 11.1 m | 1.7 % |
| Track 67W | 10.0 m | 20.7 % |

**The setting moves around inside a single fortnight** — Track 65 at 0.1 % against Track 67W
at 20.7 %, eight days apart — so measure the share for the track in hand rather than assuming
a season's worth. On Track 65 and Track 66 a stop would leave no trace at all.

## Injecting timestamps for noforeignland import

noforeignland requires time information in imported GPX — their help page says
outright that some plotters *"choose not to include the all-important time
information in their GPX exports, making it impossible to know where they should
be added to your journey."* Raymarine is one of them, so a raw export cannot be
imported.

Import route (the "GPX Exports" setting is for ingesting *your* nav software's
exports, not for downloading; there is no official way to export tracks back out):

1. Authorise the sending address: Settings → Boat tracking → GPX Imports
   (case sensitive).
2. Email the GPX to `tracking@noforeignland.com`; a reply confirms processing.

### Getting timestamped data back out of noforeignland

There is no export feature, but an undocumented JSON API serves the whole journey
*with* timestamps, unauthenticated (the browser sends only a Google Analytics
cookie):

```
https://www.noforeignland.com/api/v1/boat/journey?boatId=4718293690613760&showStories=true
```

It returns GeoJSON where each vertex is `[lon, lat, epoch_ms]`. Notes:

* 1 191 `Point` features on the `fixes` layer carry `timeMs` and a `source`
  (`GPX Export`, `NFL App`, `Manual`, `Raymarine GPX Export`, `Check in`).
* 1 191 `LineString` features hold the dense geometry — 29 614 vertices. 16 197
  unique positions carry real timestamps; the other 12 354 have `epoch 0`. Those
  are **always interior** vertices, and the endpoints of their own LineString are
  always timed, so their times can be interpolated if ever needed.
* Full range 2021-06-15 .. 2025-09-16. The HTML embed at
  `/home/embed/map/show/<boatId>/...` exposes the same 28 185 positions but
  without any time, so it is strictly inferior — don't use it.
* Note `/api/v1/boat?boatId=...` returns an encrypted blob, not useful.

Saved here as `noforeignland-journey-20260727.{json,gpx}`.

**Provenance caveat — most of 2025 is not real tracker data.** The Chinese tracker
worked in Greece but not in Bulgaria or Turkey, and the fix sources confirm it:
genuine feed data (`GPX Export`) stops after 2025-02, March adds only Raymarine
imports, and from 2025-04 onward there are just 50 hand-placed `Manual` /
`Check in` points. Treat anything after 2025-03 as approximate, and do not use it
as a precise reference fix.

### Reference fixes available for the untimestamped Raymarine tracks

| Source | Period | Quality |
|---|---|---|
| noforeignland API | 2021-06 .. 2025-02 | good (real tracker feed) |
| noforeignland API | 2025-04 .. 2025-09 | poor — 50 hand-placed points only |
| Organic Maps phone export (`My Places.kmz`) | 2025-07-30 .. 2026-07-27 | good, dense (228 097 fixes), but includes flights and land travel |
| boattracker JSON/GPX in this directory | 2023-12-30 .. 2024-01-01 | good but only a 3-day anchoring episode at Dubrovnik |
| diary (`~/solveig/diary-202401.md` for 2025, `diary-2026.md` for 2026) | 2023-06 .. 2026-07 | dates plus clock times, needs manual reading |

Only `Tracks202607.gpx` (tracks 46–60) falls in the phone-export window;
`TracksQ.gpx` and `TracksC.gpx` were exported in March 2025 and predate it, so any
apparent phone match for them is a false positive from revisiting the same
harbours. Position-only matching is ambiguous wherever the boat returns to a
familiar anchorage, so alignment must be sequence-consistent (monotonic in time
along the track), with the diary pinning each track to a date window first.

Known anchorage coordinates (from the boat owner):

| Place | Latitude | Longitude |
|---|---|---|
| Galata Bay | 43.171545043089274 | 27.941682556937685 |
| G G Yacht Club | 43.18995330534987 | 27.920852659309418 |
| Chaika | 43.24808325110401 | 28.03009078495046 |
| 1st Buna | 43.20440770190283 | 27.933114913389208 |

The established local convention is to inject **one** timestamped reference fix per
crop, appended at the crop boundary — this is what the `inject` parameter of
`split_to_point()` does, and every crop in this directory carries exactly one
`<time>` element with a hand-picked time, e.g.:

```xml
<trkpt lon="-3.430018275976181" lat="43.60115959568407"><time>2022-09-08T16:00:00Z</time></trkpt>
```

Times used so far are round hours taken from the diary (`~/solveig/diary-*.md`),
whose entry headings are `## <weekday> <ISO date> - <from> - <to>` and whose bodies
often give clock times for departure and arrival. Note that place names in
parentheses on a heading are land trips where the boat was *not* present, so they
must not be used as track reference fixes.

### How a crop was actually driven

`crop_raymarine_track_to_gap.py` is a library — it has no `__main__`. Every crop in
the table above was made by a throwaway driver, hand-edited per run, of this shape:

```python
from crop_raymarine_track_to_gap import find_gap

with open('raymarine_rest.gpx') as f:
    raymarine_data = f.read()

gap = {                                  # copied out of gaps.json
    "jump_from": [51.04336040514782,  1.907173320651054,  "2022-08-06T120000"],
    "jump_to":   [49.591433333333335, -2.338233333333333, "2022-08-16T000000"],
}

gap_track, rest = find_gap(raymarine_data, gap, acceptable_distance2=1500)
with open('tmp.gpx', 'w') as f:
    f.write(gap_track)
with open('raymarine_rest.gpx', 'w') as f: # NB: rewrites its own input
    f.write(rest)
```

Three things worth knowing before repeating this:

* **It rewrites its input in place.** `raymarine_rest.gpx` is the *residue* of every
  crop taken so far, so each run shrinks it further and the old content is gone —
  and it is gitignored, so git will not give it back. Copy it aside first.
* `acceptable_distance2` is the knob that has to be tuned per gap. The default is
  150 m; the run recorded above needed **1500 m**, because the plotter's nearest
  approach to the `jump_to` position was that far off.
* A `gaps.json` entry can be pasted in whole — `find_gap()` does `Point(*gap['jump_from'])`
  and `Point` is `(lat, long, ts, speed, heading)`, so the five-element form that
  `gaps.json` actually writes unpacks without editing. Any extra keys on the gap dict
  (`jump_distance`, `jump_vmg_knots`, …) are ignored.

The example above is the last run, on 2024-08-20: the 2022-08-06 → 08-16 Dover →
Guernsey jump. It is what produced the present `tmp.gpx` and the present state of
`raymarine_rest.gpx`; `tmp.gpx` accordingly ends with the injected
`49.591433333333335, -2.338233333333333` fix at `2022-08-16T00:00:00Z`.

### What belongs on the noforeignland journey

Only **sea voyages**. Land trips and longer stays at anchor or alongside do not
belong there. The diary is the authority on which voyages exist: every sea voyage
has destinations on its day heading, so

* a heading with two or more places (`2026-07-17 1st Buna - Chaika - G G Yacht Club`)
  is a voyage day;
* places in parentheses are land trips the boat did not make, and must be ignored;
* `...` on a heading marks a leg continuing from or into an adjacent day, so
  `- ... - Adra` is a voyage day, not a stay.

A heading naming only **one** place is usually a stay, but not always: some places
are large enough to sail within. Istanbul is the clear case — the 2.8 nm move on
2025-08-29, whose heading is just "Istanbul", is a genuine sea voyage. So the test
is actual boat movement, not the heading; a single-place heading with real movement
means the diary entry should be corrected rather than the track discarded.

The boat was ashore at **Marina Tortuga from 2025-09-15 until 2026-07-03**
(`2025-09-15 - Lake Varna - Marina Tortuga` .. `2026-07-03 - Marina "Tortuga" -
Lake Varna`), so there are no sea voyages in that window at all. Any alignment
that dates a track inside it is a false match.

### Dating the tracks: what worked

`Tracks202607.gpx` was dated by matching each `<trkseg>` (one continuous recording
session) against the timestamped phone fixes, taking the time window covering the
most distinct sampled points, then requiring Kendall tau >= 0.9 (times increase
along the track) and an implied average speed of 0.5–9 kn. Of 97 segments, 8
passed. Independent diary corroboration:

| Segment | Derived time (UTC) | nm | kn | Diary |
|---|---|---|---|---|
| Track 50 seg 2 | 2025-08-26 13:35 .. 08-27 18:19 | 47.2 | 1.65 | `08-26 ... Avsa` / `08-27 Avsa - ...` |
| Track 51 seg 0 | 2025-08-27 18:19 .. 08-28 08:00 | 65.3 | 4.78 | `08-28 ... - Istanbul` |
| Track 52 seg 0 | 2025-08-28 08:00 .. 14:08 | 17.5 | 2.84 | `08-28 ... - Istanbul` |
| Track 52 seg 2 | 2025-08-29 11:37 .. 12:13 | 2.8 | 4.75 | `08-29 - Istanbul` — movement within the city |
| Track 53 seg 0 | 2025-08-30 14:09 .. 08-31 03:16 | 56.0 | 4.35 | `08-30 Istanbul - Black Sea` / `08-31 Black Sea - Varna` |
| Track 58 seg 16 | 2026-07-10 15:47 .. 18:21 | 7.8 | 2.28 | `07-10 Varna Lake (Tortuga) - Beloslav` |
| Track 59 seg 1 | 2026-07-11 15:45 .. 16:19 | 2.5 | 4.75 | `07-11 Beloslav - ... - Galata Bay` |
| Track 59 seg 12 | 2026-07-17 07:35 .. 08:36 | 4.2 | 4.21 | `07-17 1st Buna - Chaika - G G Yacht Club` |

Result: `raymarine-voyages-timestamped.gpx` — 6 620 points, decimated to ~1 per
50 m, depth soundings preserved, XML-validated, times monotonic within every
segment. Reference times are real phone fixes within 120 m; intermediate times are
interpolated by cumulative along-track distance between them, and nothing is
extrapolated beyond the matched range.

**Coverage is only 22 % of the track points**, because the method fails
structurally where it cannot work: 47 segments are stationary (a boat at anchor
gives no time ordering, and every previous visit to that anchorage matches equally
well), 14 have no phone coverage, and ~28 passages had the phone ashore or off.

To reach the rest without inventing anything, align the *sequences*: the diary
lists 46 voyage days (73 legs) over the same period and the plotter writes tracks
in order, so the ordered list of passage segments (42 of them, displacement >= 2 nm)
can be matched monotonically onto the ordered list of voyage days, pinned by the 7
correspondences above. That needs no place coordinates.

### Diary days that understate the boat's movement

Checking this must **not** use noforeignland data: its gaps are exactly what we are
looking for, so absent NFL fixes would hide the very days that need attention.
Independent evidence instead comes from phone fixes that lie within 120 m of
Raymarine track geometry — the plotter only runs when the boat is in use, so
coincidence plus a boat-like speed (1–12 kn) between successive fixes indicates
the boat moving, while walking a pontoon or driving a coast road is filtered out.

Of 543 diary days that look like stays (one place named, no `...`), exactly one
shows real boat movement:

| Date | Heading | Boat-like movement | Notes |
|---|---|---|---|
| 2025-08-29 | `- Istanbul` | **19.5 nm** over 205 on-track phone fixes | far more than the 2.8 nm segment dated above — there is more Istanbul sailing that day still to recover |

Seven further days were flagged and then rejected: 2025-11-09, 2025-11-22,
2026-04-27, 2026-04-29, 2026-05-03, 2026-05-09 and 2026-05-19 all fall inside the
Marina Tortuga haul-out, when the boat could not move at all. They are the phone
travelling on land over water the boat had sailed in a previous season — a useful
confirmation that the detector's failure mode is understood.

Coverage limit: 420 of the 543 apparent stay days have no phone data (they precede
2025-07-30), so they cannot be checked this way at all. Anything earlier would need
a different independent source.

### How noforeignland stores an imported track

An emailed GPX becomes **one journey fix**, timestamped at the track's last point,
with the dense geometry attached to it. So point density does not clutter the fix
list, and one email per voyage leg gives one fix per leg.

**The importer deduplicates by position.** Re-sending a corrected version of a
segment whose end position already has a fix is a silent no-op: the correction never
appears and nothing reports an error. Two corrections were lost this way before it
was noticed. To fix a wrongly dated upload, **delete the old fix in the app first,
then re-send.**

There is no API for deleting; it has to be done in the app. The read-only
`/api/v1/boat/journey` endpoint is the way to verify what actually landed — compare
`fixId` sets before and after, and check that the `Raymarine GPX Export` count rose
by exactly the number of messages sent.

### Before uploading: check for duplication, and check the line not the endpoint

noforeignland attaches up to 50 nm or more of geometry to a single fix, so **a segment
can lie entirely inside an existing line while its end point is nowhere near any fix**.
Testing "is there a fix within 60 m of this segment's end?" is therefore worthless as a
duplicate check. That mistake produced the whole March 2025 batch: 21 of its 22 uploads
duplicated geometry an earlier import already held, because the earlier import had
attached 579 nm of March track to just 17 fixes.

`historic/audit_duplicates.py` does it properly. Two further traps it avoids:

* measure **point-to-segment** distance against the existing line, not distance to its
  vertices — those sit about 550 m apart, so a 100 m vertex test undercounts badly;
* **constrain by time** — following water sailed in a previous season is not
  duplication, and without a time window every track in the Aegean looks redundant.

A quick way to tell real recorded track from hand-placed points in the baseline: look at
vertex count, not distance. 501 nm of "geometry" across August 2025 came from 56
vertices — straight lines between hand-placed fixes. March's 579 nm came from 1250
vertices, which is genuine recorded track.

### Source branding: noforeignland reads the GPX `creator` attribute

The label a fix gets — `Raymarine GPX Export` versus plain `GPX Export` — comes from the
`creator` attribute of the uploaded GPX. Files whose creator contains "raymarine" are
branded as plotter exports.

So **anything not originating from the plotter must keep "raymarine" out of `creator`**.
Positions derived from photographs, or a waypoint chain built from place coordinates,
are not plotter data and must not claim to be. Times sourced from elsewhere are fine to
brand as Raymarine, since the *track* is still the plotter's; it is the positions that
determine this.

### Techniques that worked for dating segments

Ranked by how much confidence they earn:

1. **Unique-visit reference fixes.** A place visited exactly once pins its segment absolutely.
   Port Palace (moored inside once) matches exactly one segment in 147 784 points, at
   98 m; the third buna (one attempted landing) matches exactly one, at 12 m. Ask the
   owner which places were visited once — it is the highest-value question available.
2. **Segment chaining.** Segments run consecutively, so if segment *n* ends where
   *n+1* begins, dating either one dates both. This is what finally placed
   `Track 56 s3`, and it also exposed three of my own misdatings: I had assumed
   `s4` began at the lake when it actually begins at the buna where `s3` ends.
3. **Photograph timestamps.** Reliable (phone clock). Geotags are **not** —
   a 2025-09-08 photo reads 3 nm from where the owner places it. Use the times, treat
   the coordinates as corroboration only.
4. **Diary clock times**, remembering these are local: Bulgaria is UTC+3 in summer.
   Three independent cross-checks confirmed phone-derived UTC times this way.
5. **Owner recollection**, cross-checked against geometry — e.g. "dark when I reached
   the third buna" is consistent with sunset at Varna and the buna falling 92 % along
   a segment whose arrival time is known.
6. **Phone-fix matching**, but only *after* the day is already fixed by something
   above. Searching the whole timeline fails: the boat revisits the same anchorages,
   and the same waters were sailed again after the haul-out.

Accuracy needed is modest — a fix spans a day or more, so an hour or two of error
does not affect placement.

### Telling a land visit from a boat journey in the phone data

The phone export is the owner's own movement, not the boat's, and mixes passages
with flights, buses, biking and walking. The owner's rule for separating them, which
needs no coastline data:

* a land visit almost always **starts at one of the places named in the diary**;
* it starts **rarely less than ten minutes** after the boat has stopped, or has begun
  drifting slowly around the anchor;
* it **ends at the same point** it started from.

The return-to-the-same-point condition is the strong one. The exception is when the
owner leaves the boat and the crew sails on, rejoining later — and those are always
described in the diary's free text, so the diary settles the ambiguous cases.

This would have caught the false positives found earlier: seven days flagged as boat
movement during the Marina Tortuga haul-out were round trips from the yard, on water
the boat had sailed in a previous season. An earlier crude filter — "within 60 m of
water the boat is known to have sailed" — cannot distinguish those, and also fails
anywhere the track density is low.

### Hand-editing these files is error-prone

Two of the eight hand-edited crops are **not valid XML** and would be rejected by
any parser, noforeignland's importer included:

* `benelux.gpx` — `<time>2022-08-06T12:00:00Z/>` is missing its closing tag, and
  the file closes `</trk>` without closing `<trkseg>`
* `france.gpx` — closes `</trk>` without closing `<trkseg>`

(`split_to_point()` appends the correct `"</trkseg></trk></gpx>"`; these two files
lost the `</trkseg>` in manual editing.) Prefer scripting timestamp injection over
editing by hand, and validate with `xml.etree.ElementTree.parse()` before sending
anything to `tracking@noforeignland.com` — the import is one-way and lands directly
on the public track.

## Deduplication

Because coordinate strings are byte-stable within one plotter's exports, exact
set comparison on `(lon, lat)` string pairs is a sound dedup test, and each
successive export from the plotter contains a *disjoint* set of new tracks rather
than a superset of the previous one. Do not assume the newest export supersedes
the older ones — it does not.

Removed as provably redundant (2026-07-27, zero unique points lost, verified by
comparing point sets, depth values, track names and GUIDs):

* `ToSantorini2024.gpx` — its single track was byte-identical inside `TracksQ.gpx`
* `TracksXX.gpx`, `TracksSa.gpx~`, `#TracksSa.gpx#` — copies/fragments of `TracksSa.gpx`
* `#TracksQ.gpx#`, `TracksQ.gpx~` — emacs cruft, identical to `TracksQ.gpx`
* `#ToSantorini2024.gpx#` — emacs cruft
* `TracksSa.gpx` — every one of its 31 217 points, all 24 396 depth values and all
  4 track GUIDs were already present in the crops listed above
