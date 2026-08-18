# noforeignland journey chapters

A chapter is a named marker on the journey timeline: **a title and a start date**, nothing
more. The site slices the journey at each chapter start, so a chapter's span is implied by
the next chapter's start, and its `miles`/`days` are computed server-side.

Unlike the GPX upload path (`journey/NFL-EXPORT-LOG.md`), chapters are *not* mail-driven — they go
over a JSON endpoint used by the web UI. There is no published API for this; everything
below was observed by tapping `fetch`/`XHR` in the browser while creating and deleting
chapters by hand on 2026-08-02, and may change without notice.

## The endpoint

One endpoint does create, update and delete, for all chapters at once:

```
POST https://www.noforeignland.com/api/v1/boat/journey/config
Content-Type: application/json
```

Authentication is the same `authorization:` JWT that every other write uses — see
`boattracker.nfl.nfl_auth` for what the credential is and how to capture one. **Cookies play no
part.** (An earlier draft of this file claimed cookie auth; that was inferred from a captured
request whose headers were unreadable, and it was wrong.) So chapters can be scripted
head-lessly, with no browser involved:

```
python3 boattracker.nfl.nfl_auth --check
python3 boattracker.nfl.chapters_from_diary --post
```

### Create (observed)

```json
{
  "boatId": 4718293690613760,
  "showJourneyFrom": -86400000,
  "chapters": [
    {"id": 4209, "boatId": 4718293690613760, "name": "test chapter", "start": 1773097200000, "miles": 0, "days": 0},
    {"id": 0, "name": "test chapter 2", "start": 1767654000000},
    {"id": 0, "name": "test chapter 3", "start": 1723672800000}
  ],
  "deleteChapterIds": []
}
```

### Delete (observed)

```json
{
  "boatId": 4718293690613760,
  "showJourneyFrom": -86400000,
  "chapters": [],
  "deleteChapterIds": [4209, 4210, 4211]
}
```

### Field semantics

| Field | Meaning |
|---|---|
| `chapters[].id` | `0` means **create**; a non-zero id means **update that chapter** |
| `chapters[].name` | the title |
| `chapters[].start` | epoch **milliseconds**. The web UI writes local midnight, but the API keeps a **time of day**: `2026-07-03 09:30:00` was stored and read back exactly. Date-only is a picker limitation, not a data one |
| `chapters[].miles`, `.days` | derived server-side; sent as `0` on update and recomputed. Do not bother filling them |
| `deleteChapterIds` | ids to remove, independent of the `chapters` list |
| `showJourneyFrom` | **not a chapter field** — a journey-wide display setting that rides along in the same blob |

Read back with the same endpoint the export log already uses:

```
GET https://www.noforeignland.com/api/v1/boat/journey?boatId=4718293690613760&showStories=true
```

`chapters` sits next to `geojson`, `stories`, `days`, `countries`, `status`, `miles`.

## Four things that will bite

**`start` is local midnight, not UTC midnight.** The web UI builds it from the browser's
timezone. `1773097200000` is `2026-03-09T23:00:00Z` — i.e. 2026-03-10 00:00 in `Europe/Oslo`
(CET, UTC+1). A summer date lands on `22:00:00Z` instead (CEST, UTC+2). A script that uses
UTC midnight will place chapters a day early for a Norwegian reader, so pick the convention
deliberately rather than by accident.

**An empty chapter list does not mean no chapters — it means six.** With every stored
chapter deleted, the read endpoint returns *synthetic* per-calendar-year chapters:

```json
{"id": 0, "boatId": 0, "name": "2021", "start": 1609459200000, "miles": 779, "days": 365}
```

They are recognisable by `id: 0` **and** `boatId: 0`, and their `start` is genuine *UTC*
midnight on 1 January — a different convention from the real ones. They are generated, not
stored. **Read-modify-write is therefore a trap**: fetch, append one chapter, POST the lot
back, and the six defaults go up as `id: 0` records and become six permanent real chapters.
Filter on `boatId !== 0` before echoing anything back.

**The POST carries the whole journey config.** `showJourneyFrom` is in the same body, so a
hand-built request that omits it may reset a journey display setting that has nothing to do
with chapters. Echo back whatever the UI last sent.

**Whether omission alone deletes is untested.** In the observed delete, the ids were listed
in `deleteChapterIds` *and* absent from `chapters`. Nothing proves which of the two did the
work. Use `deleteChapterIds` explicitly and do not rely on omission.

## Building chapters from the diary

The diary's first-level headings *are* a chapter scheme already — "First trip to Greece",
"Bulgaria and Romania", "The not so innocent passage" — so they need no rewriting.
`boattracker.nfl.chapters_from_diary` extracts them, taking each chapter's start from the first
dated `##` day entry under the heading. `--post` creates and retitles them; `--js` emits an
equivalent console snippet for when no live token can be captured.

`--post` **reconciles against what is stored, keyed on the start instant**, so it is safe to
re-run: a heading whose title changed is still stored at the same instant, so its chapter is
re-sent with its own id and *renamed in place* — no delete, no new id, no window in which the
journey is short a chapter. Only a heading whose first dated day entry moved to another date
leaves a stored chapter with nothing pointing at it, and `--post` refuses rather than strand
one; `--replace` puts those ids in `deleteChapterIds` in the same request.

(Before 2026-08-05 every chapter went up with `id: 0`, so re-running duplicated the lot and
`--replace` had to delete all nineteen and recreate them. Three retitled 2023 headings were
what made that too blunt a tool.)

**`--js` was not converted and still sends everything with `id: 0`.** It is the
no-token fallback, it cannot read the stored ids back before it runs, and running it against
a boat that already has chapters duplicates them. Use `--post` unless the token path is
genuinely unavailable.

**Chapters starting before the first diary chapter are never deleted, by either flag.** The
diaries only exist in this format from 2023-06; anything earlier is hand-built and no file
could regenerate it. Those chapters are also re-sent with their own ids rather than merely
left out of `deleteChapterIds`, because whether omission alone deletes is untested (above)
and that is not a thing to discover on live data. `replaceable()` draws the line and
`reconcile()` decides what happens inside it; `test_chapters_from_diary.py` pins both.

There are 19 across the five diary files, from 2023-06-01. The journey itself starts 2021-06,
so roughly two years sit before the first chapter; whether the site renders that as an
untitled lead-in is untested.

The server-computed `miles`/`days` that come back are a free check on the dates: a chapter
the diary describes as a land stay should return 0 nm, and a passage chapter should return
a lot of miles in few days. Both held when the first batch was created.

## Where a chapter appears on the map, and why it looks wrong

A chapter is drawn from the **first recorded fix inside its time window** — the site has
nothing else to place it by. A moored or hauled-out boat records nothing, so a boundary
falling inside a silence snaps to wherever movement next happened, and the previous
chapter ends at wherever movement last stopped. The two are different places, which reads
as a rendering bug and is not one: it is missing data, faithfully drawn.

Measured across the 19 chapters (`silence` is the gap between the fixes either side of the
boundary, `apart` the distance between them):

| Chapter start | Silence | Apart | Renders at |
|---|---|---|---|
| 2025-06-05 and 2025-07-05 | 779 h | 3.38 nm | Galata Bay +0.34 nm — **both**, the same pair |
| 2025-07-23 | 63 h | 1.47 nm | 1.47 nm NE of G G Yacht Club, in open water |
| 2025-09-16, 2025-12-31, 2026-03-06, 2026-07-03 | 7051 h | 2.51 nm | G G Yacht Club +0.79 nm — **all four**, the same pair |

Ten of the nineteen boundaries sit in a silence longer than a day. The winter ashore is a
294-day gap, so four consecutive chapters have literally the same rendered start point.

The remedy is a position fix at the boat's actual berth, timestamped at the chapter start —
not a change to the chapter. `journey/PLACES.md` already holds the coordinates (G G Yacht Club,
Marina Tortuga, Galata Bay). Since the API keeps a time of day, a fix and a chapter can be
placed at the same instant.

`boattracker.nfl.add_fixes` does this; `boundary-fixes-plan.json` is the plan that was run on
2026-08-03. Eight fixes were added, one per boundary, each a minute after the chapter start
so it falls inside the window whichever way the comparison is written. Every one of the
eight chapters now renders **at the berth, +0.00 nm**, against offsets of up to 2.51 nm
before.

**A line straddling a boundary is drawn in both chapters.** That is a different failure from
the one above, and it has a different cure. If the geometry either side of a boundary hangs
off a single fix — an undated track that the importer stamped with one arrival time — then
no chapter edit and no added fix will separate it, because both chapters legitimately
contain part of that one line. The 2022-07 Polish coast passage showed this: 466 nm on one
timestamp, drawn twice. **Adding bare position fixes there made it worse**, laying straight
2-vertex chords across the real track; they were deleted again. The cure is to re-date the
track — split it into legs, each with its own arrival — which is `journey/NFL-EXPORT-LOG.md`'s job,
not this document's.

Before concluding a stretch is unrecorded, check the **LineStrings**, not just the Point
fixes. Point features alone made a fully-recorded 466 nm passage look like a 298-day silence.

**Use a pair of berth fixes, not one.** The owner's refinement, 2026-08-08, from watching the
2022-09 La Rochelle boundary. One fix *at* the chapter start gives the new chapter somewhere
to render, but the **preceding** chapter still has to end somewhere, and it runs on to the
next fix it can find. Where that next fix is the new chapter's first, the same fix is drawn
in both — which is what "the first outbound fix seems to be included in both chapters" looks
like from the map.

At La Rochelle the boat lay nine days (08-27 to 09-05) with the boundary at 09-04 00:00 in
the middle of it, so the old chapter reached forward to 09-05 at Île-d'Aix, **8 nm away**.
Two fixes at the berth, one an hour either side of the boundary, make the shared point the
berth instead: the overlap becomes zero-length and invisible rather than an 8 nm leg drawn
into the wrong chapter. Both are `Manual`, at identical coordinates, and both exist.

Note this is the *first* failure mode below, not the second: the geometry did not straddle
the boundary, the chapter simply had no fix of its own inside the stay.

**Same-position fixes do not merge.** Four of the eight went to identical coordinates, and
all four exist separately, with `source: Manual`. The silent merge-within-a-few-metres
described in `journey/NFL-EXPORT-LOG.md` belongs to the **GPX email importer**, not to
`POST /api/v1/boat/fix`. This was verified with a two-fix probe before the rest were sent.

**An empty chapter is the extreme case, and the journey had one.** `2014-05: All tracks lost
prior to summer 2021` runs 2014-05-01 → 2021-05-13 and contained **no fix whatever**, so it
rendered at the 05-13 Sandspollen anchorage, 24 km south of the boat and inside the next
chapter's water. There was no berth position to give it until the 2021-05-01 tracker day
turned up in the second archive location — 736 fixes inside 26 m of the Bærum berth. One
`Manual` fix there on 2026-08-11 (`6755398653083167`) ends it, and the chapter still reports
**0 nm**, which is how you tell a position was added and not a passage.

That fix breaks the journey's "only sea voyages" rule on purpose, and it is the only case in
this document where a *day* rather than a boundary instant carries the fix — the boundary is
seven years earlier and there is nothing to sit beside. Note also that its title was **not**
changed: "Almost all tracks lost" was proposed on the reasoning that a surviving tracker day
falsifies "all tracks lost", and the owner ruled against it the same day, because a stationary
day is a position and not a track. Renaming would have said something untrue in order to
describe something true.

Still unfixed, for want of coordinates: the four hand-built 2022 chapters, `2023-06-01`
(Algés) and `2023-11-20` (Rome). Renaming a chapter does not touch where it renders — the
2023 retitling on 2026-08-05 left both of those offsets exactly as they were.

## Hand-built chapters, and the plan as desired state

`plans/chapters-pre2023.json` lists every chapter the diaries cannot produce, and
`add_chapters.py` treats it as **desired state** rather than a list of insertions: an entry
already stored at that instant is left alone, or renamed if the plan now gives it a
different name, and `--prune` deletes stored pre-diary chapters the plan no longer lists.
Renaming is not a nicety — condensing several chapters into one keeps the earliest start,
which collides with the chapter already there, and without the rename path the survivor
would silently keep its old title.

`--prune` is bounded by the first diary chapter's start, so it cannot reach a chapter the
diaries own however the plan is edited. `test_add_chapters.py` pins that.

### The 2021 Oslo–Gothenburg chapters, condensed and then split again

The four original 2021 chapters were **condensed** on 2026-08-03 into
`Travels between Oslo and Gothenburg - alone, with my daughter and with the family`, because
the 2021 tracks were missing and three of the four read 0 nm. JSON has no comment syntax, so
the superseded split is recorded here:

```json
 ["Going alone from Oslo to Gothenburg", "2021-05-13"],
 ["Going with my family from Gothenburg to Oslo", "2021-05-29"],
 ["Going with my daughter from Oslo to Gothenburg", "2021-06-29"],
 ["Going with family from Gothenburg to Oslo", "2021-07-14"],
```

With the tracks recovered, one chapter then held **842 nm over 98 days** — every Oslofjord
local sail of the summer in the same slice as two North Sea round trips — and the owner asked
on 2026-08-05 for **three** chapters instead, and on 2026-08-06 for a **fourth** — a second
Oslofjord summer after the family trip, deliberately carrying the same name as the first.
Each boundary is a date the material actually supports, not a guess:

| start | chapter | why there |
|---|---|---|
| 2021-05-13 | `Alone to Gothenburg, back with the family` | unchanged; renamed in place, id 4279 |
| 2021-06-06 | `Summer in the Oslofjord` | the day **after** the round trip closed. The arrival fix at Kadettangen is 06-05 17:08 UTC, so starting on 06-05 would have cut the homecoming leg in half and drawn it in both chapters |
| 2021-06-29 | `2021-07: To Gothenburg with my daughter, back with my family` | the tracker has the boat leaving Bærum that afternoon and 23 nm south by 21:29; the diary puts him at Fornebu on 06-28 and in Tønsberg with his daughter on 07-01. **Labelled `2021-07`**, against its own start date — see below |
| 2021-07-22 | `Summer in the Oslofjord` | the same rule as 06-06: the passage home ends 07-21 19:57 local at the Bærum berth, and 07-22 is a fresh local sail into central Oslo. The diary's *"back in Oslo again by 22nd of July"* is that day, not the arrival |

Server-computed miles are the check, and all four are plausible: **338 nm / 24 d**,
**18 nm / 23 d**, **404 nm / 23 d**, **91 nm / 28 d** — the two Oslofjord chapters read as
local sailing, which is what those totals mean, and the pair either side of them sum to what
the single chapter reported.

**The repeated name is intentional**, and the period prefix is what distinguishes
`2021-06: Summer in the Oslofjord` from `2021-07: Summer in the Oslofjord` — two summers in
the same water bracketing the trip south. It is not a collision: the instants are distinct,
and `test_add_chapters.py` pins that no two plan entries ever share one, which *would*
collapse silently in the rename-or-add matching.

### A chapter may state a period its start date contradicts

The daughter/family trip starts **2021-06-29** and ends 07-21, so it is a July trip that
happens to sail on the last Tuesday of June. `chapter_name()` normally derives the prefix
from the start date, which labelled it `2021-06`; **a title in the plan that already opens
with `YYYY-MM: ` is now left alone**, so `chapters-pre2023.json` says `2021-07:` and means it.

The alternative was moving the start to 07-01, and that would have been wrong twice over: the
06-29 and 06-30 legs south would fall into the Oslofjord chapter, and this one would render at
Tønsberg instead of the Bærum berth it left from. A label is the cheap thing to bend; a
boundary is not.

The rule also makes `chapter_name()` **idempotent**, which is worth more than the feature
itself. `add_chapters.py` compares stored names — which carry prefixes — against freshly built
ones, so without it a second pass would build `2021-07: 2021-07: …`, read as a rename, and
retitle the chapter on every single run. `test_chapters_from_diary.py` pins both, and pins
that a title merely *containing* a date (`The 2024-06 passage`) is still prefixed normally.

**A prefix repeats either way**, and that is a property of the season, not of the scheme:
three chapters span June to August, so two of them share a month whichever way it is labelled.
The repeat moved from `2021-06` to `2021-07` and accuracy is what was bought.

**Spelling: `Oslofjord`, one word.** It is the standard English rendering and the Norwegian
name, against `Oslo Fjord` and `Oslo fjord`; the rest of this repo already used it, and the
2026-08-05 chapter name that did not was corrected the next day.

Note what splitting does **not** do: it does not touch geometry. The straight chords across
the 2021 holes — 51 nm from Akerøy fort home on 06-05, 23 nm across the 07-16 feed break,
10 nm across the 07-02 hole — are unchanged, and the first of them now sits at the end of a
chapter rather than in the middle of one.

### Where the Poland delivery starts — settled 2026-08-06

The boat left Kadettangen on the evening of **08-13**, ran 44 nm south to Tønsberg on 08-14,
lay there 08-15 .. 08-20, and sailed for real on **08-21**. So the 44 nm was either the last
Oslofjord sail or the first leg to Poland, and the track alone cannot tell them apart: the
same passage, the same direction, either way.

**The owner settled it on what he did, not what the boat did**: *"the fact that I left the
boat in Tønsberg and went to Oslo settles it"*. A delivery is not under way while the crew has
gone home. So the 44 nm belongs to `2021-07: Summer in the Oslofjord`, and the chapter starts
at the departure — **08-21**, moved from 08-19 with `--prune`. This was `--prune`'s first run
against live data and it behaved: one delete, one create. Note that a *moved* start is
necessarily a new row — the plan keys on the instant — so id 4283 is gone and the chapter has
a fresh id. Renaming preserves ids; re-dating cannot.

That is a rule worth keeping, and it generalises: **a chapter boundary follows the crew, not
only the hull.** The `ashore` discipline in `journey/TRACKS-2021.md` is the same idea one level down —
there it stops a flight to Tromsø being drawn as a passage, here it stops six days at a berth
being drawn as a delivery.

08-19 was never more than a compromise: it came from the diary's *"I was in Oslo the 19th of
August"*, which is a fact about the owner and, read properly, is evidence for the **opposite**
boundary. Nothing moves between 08-15 17:04 and 08-21 20:03, so the move changed no geometry
and no mileage — both chapters kept 91 nm and 733 nm exactly, and only the day counts shifted,
28 → 30 and 27 → 25. That equality is itself the proof that the six days were a stop.

## Current state

As of 2026-08-06 the boat has **30 chapters**: the 19 from the diaries plus eleven hand-built
ones running back to a `2014-05` placeholder for the era whose tracks are lost. Every name
carries its period, as `2025-07: Family trip to Turkey` — the list shows no dates otherwise,
and the synthetic year-chapters it replaced did carry the year. That period is the start
month except where a plan entry states its own, which one 2021 chapter does. Ten manual fixes
were added on 2026-08-03: eight at chapter boundaries, two in the Gdansk yard. An eleventh
followed on 2026-08-11, at the 2021-05-01 Bærum berth, for the empty `2014-05` placeholder
(above).

The three 2023 chapters were retitled on 2026-08-05, from the owner's edits to the diary
headings, by `chapters_from_diary.py --post` alone — ids 4255/4256/4257 unchanged:

| was | now |
|---|---|
| `2023-06: Tur fra Algés til Menorca` | `2023-06: From Algés to Menorca, with family most of the way` |
| `2023-09: Diary Menorca to Rome` | `2023-09: Menorca, Sardinia, Tiber (Rome)` |
| `2023-11: From Rome to Dubrovnik` | `2023-11: From Tiber (Rome) to Dubrovnik` |

The 0 nm this section used to flag against `2022-09: Sailing towards the Mediterranean
without family` is gone — it now reads **831 nm over 20 days**, the Iberian legs having been
uploaded since. `2022-09: Berlenga accident and repairs` still spans **249 days**, because
the next chapter is 2023-06; that is the diary's shape, not an error.

Sending a chapter with its real `id` **updates it in place** — no duplicate, no delete
needed. That is how the timestamp test above was run and reverted.

## How this was captured, if it needs redoing

The Chrome DevTools network pane is unusably noisy here (Cloudflare RUM and Google Analytics
outnumber the real calls). What worked was patching the page's own `fetch` and
`XMLHttpRequest.prototype.send` to push every non-GET request into a `window` array, then
performing the action by hand and reading the array back.

Store captures in a **variable, not `console.log`**: the console reader only sees messages
logged after its first invocation, so anything logged before that is lost. The tap survives
the site's client-side route changes but not a full page reload.
