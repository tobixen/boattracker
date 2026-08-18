"""Build noforeignland journey chapters from the diary's first-level headings.

Each `# ` heading in `~/solveig/diary-*.md` is one chapter; its start is the date of
the first `## ... YYYY-MM-DD ...` day entry that follows it.

Writing them needs the `authorization` JWT that `nfl_auth.py` stores; `--post` uses it
and needs no browser. `--js` remains for when no live token can be captured: it emits a
console snippet that runs inside an authenticated page instead.

    python3 chapters_from_diary.py             # list the chapters
    python3 chapters_from_diary.py --post      # create, and retitle in place; safe to re-run
    python3 chapters_from_diary.py --post --replace   # also delete stranded chapters
    python3 chapters_from_diary.py --js        # emit the console snippet

`--post` reconciles rather than inserting: a chapter already stored at a heading's start
is updated by id, so an edited heading is a rename and nothing is deleted or recreated.
Only a heading whose *date* moved leaves a stored chapter stranded, and that alone is what
`--replace` is needed for.
"""

import argparse
import datetime
import glob
import json
import re
import subprocess
import sys
import zoneinfo

from boattracker import config
from boattracker.nfl import nfl_auth

__getattr__ = config.lazy_module_getattr('DIARY_GLOB', 'BOAT_ID', 'JOURNEY_URL')
# Journey-wide display setting that rides along in the same config blob; echoing the
# value the web UI last sent avoids resetting it as a side effect.
SHOW_JOURNEY_FROM = -86400000
CONFIG_URL = config.CONFIG_URL
# The web UI derives `start` from the browser's timezone, so a chapter created by hand
# sits at local midnight. Matching that keeps hand-made and scripted chapters consistent.
TZ = zoneinfo.ZoneInfo("Europe/Oslo")

DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
# A stored name opens with its period, so a title already carrying one is left alone.
PERIOD_RE = re.compile(r"^\d{4}-\d{2}: ")


def collect(pattern=None):
    """Return [(date, title, source)], sorted by date.

    `pattern` defaults to the configured diary glob, resolved *here* rather than as an
    argument default: a default is evaluated when the `def` runs, which would make merely
    importing this module require a configured diary directory.
    """
    if pattern is None:
        pattern = config.DIARY_GLOB
    rows = []
    for path in sorted(glob.glob(pattern)):
        pending = None
        with open(path, encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                if line.startswith("# "):
                    pending = (line[2:].strip(), f"{path.split('/')[-1]}:{lineno}")
                elif line.startswith("## ") and pending:
                    m = DATE_RE.search(line)
                    if m:
                        rows.append((m.group(1), *pending))
                        pending = None
        if pending:
            print(f"warning: no dated day entry after '{pending[0]}' ({pending[1]})", file=sys.stderr)
    rows.sort()
    return rows


def chapter_name(date, title):
    """The stored name: `2025-07: Family trip to Turkey`.

    The synthetic year-chapters the site generates carry the year in the name, and the
    chapter list gives no other date cue, so the period is prepended explicitly.

    **A title that already states a period keeps it.** A chapter can start on the last
    days of a month and belong to the next one — 2021-06-29 .. 07-21 is a July trip — and
    the alternative, moving the start date to make the prefix come out right, would put
    the first days of the passage in the previous chapter. That makes this idempotent
    too, which matters: `add_chapters.py` compares stored names against freshly built
    ones, and a doubled prefix would read as a rename on every run.
    """
    return title if PERIOD_RE.match(title) else f"{date[:7]}: {title}"


def start_ms(date):
    """Epoch milliseconds at local midnight on `date`, matching what the web UI sends."""
    d = datetime.date.fromisoformat(date)
    return int(datetime.datetime(d.year, d.month, d.day, tzinfo=TZ).timestamp() * 1000)


def curl(args):
    """Run curl with the browser-like headers `nfl_auth` established, returning stdout.

    The 600 s cap is for the *read* path: `JOURNEY_URL` returns 2.4 MB and normally answers
    in ~2 s, but the server was slow enough on 2026-08-09 to blow a 120 s timeout in
    `reimport_journey.py`. A 30 s cap here would have failed first, and every caller that
    reads the journey before writing — `add_fixes.py`, `add_chapters.py` — goes through it.
    """
    base = [
        "curl", "-s", "-m", "600",
        "-H", "accept: application/json, text/plain, */*",
        "-H", "origin: https://www.noforeignland.com",
        "-H", f"referer: {config.REFERER}",
        "-H", "sec-fetch-dest: empty", "-H", "sec-fetch-mode: cors",
        "-H", "sec-fetch-site: same-origin", "-A", nfl_auth.UA,
    ]
    r = subprocess.run(base + args, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"curl failed ({r.returncode}): {r.stderr.strip()}")
    return r.stdout


def stored_chapters():
    """Chapters actually stored for the boat.

    A boat with none reads back *synthetic* per-year chapters carrying `id: 0` and
    `boatId: 0` — see `../NFL-CHAPTERS.md`. Filtering them out here is what keeps them
    from being echoed back and turned into permanent rows.
    """
    out = curl([config.JOURNEY_URL])
    try:
        journey = json.loads(out)
    except json.JSONDecodeError:
        sys.exit(f"could not parse the journey response: {out[:200]!r}")
    return [c for c in journey.get("chapters", []) if c.get("boatId")]


def replaceable(existing, cutoff):
    """The stored chapters `--replace` is allowed to delete.

    Only chapters starting at or after `cutoff`, i.e. the period the diaries actually
    cover. The chapters before it are hand-built — there are no diaries in this format
    from before 2023-06, so nothing could regenerate them — and deleting them would
    destroy work outright.
    """
    return [c for c in existing if c["start"] >= cutoff]


def reconcile(existing, desired):
    """Match stored chapters to the diaries by start instant.

    Returns `(matched, creates, stale)`: `matched` pairs each stored chapter with the
    diary record for the same instant — sending it back with its own id **updates it in
    place**, which is how a retitled heading is applied without deleting anything.
    `creates` are instants nothing is stored at, `stale` the stored chapters the diaries
    no longer place anywhere, which are the only ones that need deleting.

    Keying on the instant rather than the name is what makes a re-run idempotent: a
    chapter whose title changed is still the same chapter, and only a heading whose first
    dated day entry moved produces a stale row.
    """
    by_start = {c["start"]: c for c in existing}
    matched = [(by_start[d["start"]], d) for d in desired if d["start"] in by_start]
    creates = [d for d in desired if d["start"] not in by_start]
    wanted = {d["start"] for d in desired}
    stale = [c for c in existing if c["start"] not in wanted]
    return matched, creates, stale


def post(rows, replace=False):
    if not rows:
        sys.exit("no chapters found in the diaries")
    # Everything before the first diary chapter belongs to the hand-built era.
    cutoff = start_ms(rows[0][0])
    existing = stored_chapters()
    preserved = [c for c in existing if c["start"] < cutoff]
    desired = [{"id": 0, "name": chapter_name(d, t), "start": start_ms(d)} for d, t, _ in rows]
    matched, creates, stale = reconcile(replaceable(existing, cutoff), desired)

    if stale and not replace:
        print(f"{len(stale)} stored chapter(s) start where no diary heading now does:", file=sys.stderr)
        for c in stale:
            day = datetime.datetime.fromtimestamp(c["start"] / 1000, TZ).date()
            print(f"   {c['id']}  {day}  {c['name']}", file=sys.stderr)
        sys.exit("refusing to post — leaving them would strand a chapter the diaries no "
                 "longer describe. Re-run with --replace to delete these.")

    for c in preserved:
        day = datetime.datetime.fromtimestamp(c["start"] / 1000, TZ).date()
        print(f"preserving pre-diary chapter {c['id']}: {day}  {c['name']}")
    for stored, want in matched:
        day = datetime.datetime.fromtimestamp(stored["start"] / 1000, TZ).date()
        if stored["name"] != want["name"]:
            print(f"renaming {stored['id']}: {day}  {stored['name']}\n      -> {want['name']}")
    for c in creates:
        day = datetime.datetime.fromtimestamp(c["start"] / 1000, TZ).date()
        print(f"creating {day}  {c['name']}")

    body = {
        "boatId": config.BOAT_ID,
        "showJourneyFrom": SHOW_JOURNEY_FROM,
        # The preserved and matched ones are re-sent with their own ids rather than merely
        # left out of deleteChapterIds: whether omission alone deletes a chapter is
        # untested, and this is not the place to find out. A matched chapter carries the
        # diary's name, so the same request that preserves it also retitles it.
        # miles/days are recomputed server-side.
        "chapters": [
            {"id": c["id"], "boatId": config.BOAT_ID, "name": c["name"], "start": c["start"], "miles": 0, "days": 0}
            for c in preserved
        ] + [
            {"id": stored["id"], "boatId": config.BOAT_ID, "name": want["name"], "start": stored["start"],
             "miles": 0, "days": 0}
            for stored, want in matched
        ] + creates,
        "deleteChapterIds": [c["id"] for c in stale],
    }
    out = curl([
        "-X", "POST", CONFIG_URL,
        "-H", "content-type: application/json",
        "-H", f"authorization: {nfl_auth.load()}",
        "-w", "\n%{http_code}",
        "--data-binary", json.dumps(body, ensure_ascii=False),
    ])
    code = out.rsplit("\n", 1)[-1].strip()
    deleted = len(body["deleteChapterIds"])
    print(f"POST {code}" + (f" (deleted {deleted})" if deleted else ""))
    if code in ("401", "403"):
        sys.exit("token rejected — capture a fresh one, see nfl_auth.py")

    now = stored_chapters()
    print(f"{len(now)} chapter(s) now stored:")
    for c in sorted(now, key=lambda c: c["start"]):
        day = datetime.datetime.fromtimestamp(c["start"] / 1000, TZ).date()
        print(f"   {day}  {c['name']}   ({c['miles']} nm, {c['days']} d)")


def emit_js(rows):
    """Print a console snippet that creates the chapters and verifies the result.

    `start` is built with `new Date(d + 'T00:00:00')` deliberately: the web UI derives
    local midnight from the browser timezone, and matching it keeps hand-made and
    scripted chapters consistent. Only chapters with `boatId !== 0` are real — the
    synthetic per-year chapters the API returns for a boat with none must never be
    echoed back, or they become permanent rows.
    """
    src = json.dumps([[d, chapter_name(d, t)] for d, t, _ in rows], ensure_ascii=False, indent=1)
    print(f"""// Paste into the console on https://www.noforeignland.com while logged in.
const src = {src};
const body = {{
  boatId: {config.BOAT_ID},
  showJourneyFrom: {SHOW_JOURNEY_FROM},
  chapters: src.map(([d, name]) => ({{ id: 0, name, start: new Date(d + "T00:00:00").getTime() }})),
  deleteChapterIds: []
}};
const res = await fetch("/api/v1/boat/journey/config", {{
  method: "POST",
  headers: {{ "Content-Type": "application/json" }},
  body: JSON.stringify(body)
}});
const check = await fetch("/api/v1/boat/journey?boatId={config.BOAT_ID}&showStories=true").then(r => r.json());
console.log("POST", res.status, "| stored chapters:",
  check.chapters.filter(c => c.boatId !== 0).map(c => c.name));""")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--post", action="store_true", help="create and retitle the chapters via the API")
    ap.add_argument("--replace", action="store_true",
                    help="with --post: delete stored chapters no diary heading starts at")
    ap.add_argument("--js", action="store_true", help="emit the browser console snippet")
    ap.add_argument("--glob", default=config.DIARY_GLOB, help=f"diary file glob (default: {config.DIARY_GLOB})")
    args = ap.parse_args()

    rows = collect(args.glob)
    if args.post:
        post(rows, replace=args.replace)
    elif args.js:
        emit_js(rows)
    else:
        for date, title, source in rows:
            print(f"{date}  {chapter_name(date, title)}   [{source}]")
    print(f"{len(rows)} chapters", file=sys.stderr)


if __name__ == "__main__":
    main()
