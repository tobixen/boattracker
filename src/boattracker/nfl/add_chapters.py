"""Add hand-built journey chapters that no diary can produce.

The diaries only exist in this format from 2023-06, so the earlier chapters have to be
entered by hand. `chapters_from_diary.py` deliberately never deletes anything starting
before its first diary chapter, so chapters added here survive a later `--replace`.

Existing chapters are re-sent unchanged with their own ids rather than left out of the
request: whether omission alone deletes a chapter is untested (`../NFL-CHAPTERS.md`).

    python3 add_chapters.py --plan chapters-pre2023.json --dry-run
    python3 add_chapters.py --plan chapters-pre2023.json

The plan is a JSON list of `[name, when]` or `[name, when, timezone]`. `when` is an ISO
date (local midnight) or datetime; the timezone defaults to Europe/Oslo, which is what the
web UI uses, and is worth setting explicitly when the boat was in a different zone and the
time of day matters.
"""

import argparse
import datetime
import json
import sys
import zoneinfo

from boattracker import config
from boattracker.nfl import chapters_from_diary as cfd
from boattracker.nfl import nfl_auth

__getattr__ = config.lazy_module_getattr('BOAT_ID')
DEFAULT_TZ = "Europe/Oslo"


def when(text, tz):
    t = datetime.datetime.fromisoformat(text)
    if t.tzinfo is None:
        t = t.replace(tzinfo=zoneinfo.ZoneInfo(tz or DEFAULT_TZ))
    return int(t.timestamp() * 1000)


def build(rows):
    """New chapters, with the period prefix the stored names carry."""
    out = []
    for name, w, tz in rows:
        ms = when(w, tz)
        day = datetime.datetime.fromtimestamp(ms / 1000, zoneinfo.ZoneInfo(tz or DEFAULT_TZ))
        out.append({"id": 0, "name": cfd.chapter_name(day.strftime("%Y-%m-%d"), name), "start": ms})
    return out


def body(existing, rows):
    return {
        "boatId": config.BOAT_ID,
        "showJourneyFrom": cfd.SHOW_JOURNEY_FROM,
        "chapters": [
            {"id": c["id"], "boatId": config.BOAT_ID, "name": c["name"], "start": c["start"],
             "miles": 0, "days": 0}
            for c in existing
        ] + build(rows),
        "deleteChapterIds": [],
    }


def prunable(existing, desired, cutoff):
    """Stored chapters `--prune` may delete: hand-built ones the plan no longer lists.

    Bounded by `cutoff`, the first diary chapter's start, so a chapter the diaries own can
    never be deleted by this path however the plan is edited — `chapters_from_diary.py`
    is the only thing entitled to touch those.
    """
    return [c for c in existing if c["start"] < cutoff and c["start"] not in desired]


def load_plan(path):
    with open(path, encoding="utf-8") as f:
        rows = json.load(f)
    return [(r[0], r[1], r[2] if len(r) > 2 else None) for r in rows]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--plan", required=True, help="JSON list of [name, when] or [name, when, tz]")
    ap.add_argument("--prune", action="store_true",
                    help="also delete pre-diary chapters the plan no longer lists")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    rows = load_plan(a.plan)
    existing = cfd.stored_chapters()
    new = build(rows)

    doomed = []
    if a.prune:
        diary = cfd.collect()
        cutoff = cfd.start_ms(diary[0][0])
        doomed = prunable(existing, {n["start"] for n in new}, cutoff)
        for c in doomed:
            print(f"   would delete {c['id']}  {c['name']}" if a.dry_run
                  else f"   deleting {c['id']}  {c['name']}")
        existing = [c for c in existing if c not in doomed]

    # The plan file is the desired state, not a list of insertions, so re-running it must
    # be safe: a chapter already stored at that instant is left alone, or renamed if the
    # plan now gives it a different name. Renaming matters when several chapters are
    # condensed into one that keeps the earliest start.
    by_start = {e["start"]: e for e in existing}
    renamed, unchanged, to_add = [], [], []
    for n in new:
        stored = by_start.get(n["start"])
        if stored is None:
            to_add.append(n)
        elif stored["name"] != n["name"]:
            print(f"   {'would rename' if a.dry_run else 'renaming'} {stored['id']}"
                  f"  {stored['name']}\n      -> {n['name']}")
            stored["name"] = n["name"]
            renamed.append(n)
        else:
            unchanged.append(n)
    for n in unchanged:
        print(f"   already present, skipping  {n['name']}")
    new = to_add
    if not new and not doomed and not renamed:
        print("nothing to do")
        return

    for n in new:
        local = datetime.datetime.fromtimestamp(n["start"] / 1000, zoneinfo.ZoneInfo(DEFAULT_TZ))
        print(f"   {'would add' if a.dry_run else 'adding'} {local:%Y-%m-%d %H:%M %Z}  {n['name']}")
    if a.dry_run:
        return

    payload = {**body(existing, []), "chapters": body(existing, [])["chapters"] + new,
               "deleteChapterIds": [c["id"] for c in doomed]}
    out = cfd.curl(["-X", "POST", cfd.CONFIG_URL,
                    "-H", "content-type: application/json",
                    "-H", f"authorization: {nfl_auth.load()}",
                    "-w", "\n%{http_code}",
                    "--data-binary", json.dumps(payload, ensure_ascii=False)])
    code = out.rsplit("\n", 1)[-1].strip()
    print(f"POST {code}")
    if code in ("401", "403"):
        sys.exit("token rejected — capture a fresh one, see nfl_auth.py")

    now = cfd.stored_chapters()
    print(f"{len(now)} chapter(s) now stored:")
    for c in sorted(now, key=lambda c: c["start"]):
        day = datetime.datetime.fromtimestamp(c["start"] / 1000, cfd.TZ)
        print(f"   {day:%Y-%m-%d %H:%M}  {c['name']}   ({c['miles']} nm, {c['days']} d)")


if __name__ == "__main__":
    main()
