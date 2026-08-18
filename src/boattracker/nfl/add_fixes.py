"""Add noforeignland position fixes, backdated.

The app's own call, captured from the web UI on 2026-08-03:

    POST https://www.noforeignland.com/api/v1/boat/fix
    content-type: application/x-www-form-urlencoded
    authorization: <JWT>

    boatId=<id>&lat=<decimal>&lon=<decimal>&timestamp=<epoch ms>

**Form-encoded, not JSON** — unlike the chapter endpoint, which takes JSON. Auth is the
same header `nfl_auth.py` handles; cookies play no part.

`timestamp` is arbitrary: the UI's own "add position fix" backdates, writing local
midnight for a chosen date. A script can therefore place a fix at any instant, which is
what makes this useful for chapter boundaries — see `../NFL-CHAPTERS.md`.

A "check in" is the same POST plus `PUT /api/v1/boat/checkin` with a multipart body that
was not captured. Nothing here does check-ins; these are plain position fixes.

## A fix is one timestamp for a whole track

Not a position report. noforeignland hangs an entire `LineString` on this single instant,
and that line may cover minutes, hours, days or weeks — so **the timestamp posted here is
the leg's *arrival***, and the target is **one fix per leg** — a leg running from one
significant stop to the next, which the diary headings record. `../IMPROVE-TRACKS.md` states
the model in full; read it before deciding what instant to give a fix. (An earlier "about two
hours" target was withdrawn: vertices carry their own times, so a long leg is still datable.)

That is also why creating a track is a **two-step** operation and why this script is the
first step:

    python3 add_fixes.py --plan plan.json          # the fix: position + arrival instant
    python3 put_fix_path.py --fix-id <id> --path p.json   # the geometry hung on that fix

Import by email is the only way to do both at once, so this pair is the route that avoids it.

## Where a bare fix helps, and where it does damage

A one-point `Manual` fix is not always harmless, and the difference is *where it sits*:

* **Between two tracks**, at a harbour or an anchorage — **keep it.** It competes with no
  line, and it carries the one thing a fix-per-track model cannot otherwise express: a
  **departure** time, since every fix timestamp is an arrival.
* **In the middle of a track** — **it must not be there.** The renderer draws fix to fix, so
  a lone point inside a leg makes the map run to it and back out: a manufactured backtrack.
  The 2022-07 Polish coast is the worked example — fixes added there laid straight 2-vertex
  chords across real track and had to be deleted again (`../NFL-CHAPTERS.md`).

## Why this exists

A chapter is drawn from the first recorded fix inside its window. A boat sitting still
records nothing, so a chapter starting during a stay renders wherever the boat next moved
— sometimes miles away, and in a different place from where the previous chapter ended.
A fix at the berth, timestamped at the chapter start, puts both where they belong.

## Before running

Take a snapshot into `../nfl-snapshots/`. Unlike a deletion this is reversible — the fixes
come back with their own fixIds and `delete_fixes.py` removes them — but knowing the
before state is what makes it reversible in practice.

Beware the importer's silent merge: a new fix within a few metres of an existing one is
absorbed with no error (`../NFL-EXPORT-LOG.md`). Verify against the journey endpoint
afterwards rather than trusting HTTP 200.

    python3 add_fixes.py --plan plan.json --dry-run
    python3 add_fixes.py --plan plan.json

The plan is a JSON list of `[lat, lon, when, description]`, where `when` is an ISO date
(local midnight) or an ISO datetime.
"""

import argparse
import datetime
import json
import subprocess
import sys
import time
import urllib.parse
import zoneinfo

from boattracker import config
from boattracker.nfl import chapters_from_diary as cfd
from boattracker.nfl import nfl_auth

__getattr__ = config.lazy_module_getattr('BOAT_ID')
URL = config.FIX_URL
TZ = zoneinfo.ZoneInfo("Europe/Oslo")


def when(text):
    """Epoch milliseconds from an ISO date or datetime, interpreted as local time."""
    t = datetime.datetime.fromisoformat(text)
    if t.tzinfo is None:
        t = t.replace(tzinfo=TZ)
    return int(t.timestamp() * 1000)


def payload(lat, lon, timestamp_ms):
    """The form-encoded body, with coordinates at full precision."""
    return urllib.parse.urlencode({
        "boatId": config.BOAT_ID,
        "lat": repr(float(lat)),
        "lon": repr(float(lon)),
        "timestamp": int(timestamp_ms),
    })


def load_plan(path):
    with open(path, encoding="utf-8") as f:
        rows = json.load(f)
    return [(float(lat), float(lon), str(w), str(desc)) for lat, lon, w, desc in rows]


def existing_timestamps():
    """The `timeMs` of every point fix on the journey.

    These endpoints do not merge by position (see `../NFL-CHAPTERS.md`), so re-running a
    plan would silently create duplicates. Matching on the timestamp is enough: the values
    here are minute-precise instants chosen by a plan, not something two fixes land on by
    coincidence.
    """
    j = json.loads(cfd.curl([cfd.JOURNEY_URL]))
    return {f["properties"].get("timeMs") for f in j["geojson"]["features"]
            if f["geometry"]["type"] == "Point"}


def post(lat, lon, timestamp_ms, token, timeout=30):
    r = subprocess.run(
        ["curl", "-s", "-m", str(timeout), "-o", "/dev/null", "-w", "%{http_code}",
         "-X", "POST", URL,
         "-H", "accept: application/json, text/plain, */*",
         "-H", "content-type: application/x-www-form-urlencoded",
         "-H", f"authorization: {token}",
         "-H", "origin: https://www.noforeignland.com",
         "-H", f"referer: {config.REFERER}",
         "-H", "sec-fetch-dest: empty", "-H", "sec-fetch-mode: cors",
         "-H", "sec-fetch-site: same-origin", "-A", nfl_auth.UA,
         "--data", payload(lat, lon, timestamp_ms)],
        capture_output=True, text=True)
    return r.stdout.strip()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--plan", required=True, help="JSON list of [lat, lon, when, description]")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    rows = load_plan(a.plan)
    present = existing_timestamps()
    todo = [r for r in rows if when(r[2]) not in present]
    for lat, lon, w, desc in rows:
        if when(w) in present:
            print(f"   already present, skipping  {desc}")
    print(f"{len(todo)} fix(es) to add")
    ok = bad = 0
    token = None if a.dry_run or not todo else nfl_auth.load()
    for lat, lon, w, desc in todo:
        ms = when(w)
        local = datetime.datetime.fromtimestamp(ms / 1000, TZ)
        label = f"{lat:.6f},{lon:.6f}  {local:%Y-%m-%d %H:%M %Z}  {desc}"
        if a.dry_run:
            print(f"   would add {label}")
            continue
        code = post(lat, lon, ms, token)
        if code == "000":  # connection failure, worth one retry; a 4xx is not
            time.sleep(2)
            code = post(lat, lon, ms, token)
        print(f"   HTTP {code}  {label}")
        if code == "200":
            ok += 1
        else:
            bad += 1
            if code in ("401", "403"):
                print("   token rejected — capture a fresh one and re-run the remainder",
                      file=sys.stderr)
                break
        time.sleep(1)
    if not a.dry_run:
        print(f"\n{ok} added, {bad} failed")
        print("verify against the journey endpoint — a fix within a few metres of an "
              "existing one is merged silently")


if __name__ == "__main__":
    main()
