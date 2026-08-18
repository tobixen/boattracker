#!/usr/bin/env python3
"""Read the Organic Maps phone export (KMZ or KML) into timestamped fixes.

The phone is the project's densest source of *time* after the on-board tracker, and
since the tracker stopped it is often the only one. `ORGANICMAPS-SYNC.md` explains how
the file gets onto the laptop; this module is the reader every consumer should use
instead of parsing the KML again.

## Two traps this module exists to absorb

**The namespaces are mixed.** Inside `<gx:Track>` the coordinates are `<gx:coord>` but
the timestamps are plain `<when>` — KML namespace, not gx. A reader that asks for
`gx:when` gets a track with the right number of points and **zero** timestamps, which
looks like an export without times rather than a parsing bug.

**The clock glitches.** The 2026-08-14 export carries a fix dated 2045-08-02 in the
middle of an otherwise ordered track. Anything using these fixes to date plotter
geometry must drop such a fix rather than believe it, so `load()` filters by year by
default; pass `max_year=None` to see everything.

The export is cumulative and overlapping: each new file repeats the earlier tracks and
adds the days since. Reading the newest file is enough.

Usage:
    python3 omaps_export.py "~/Downloads/newmi/My Places (2).kmz" --days
"""
from __future__ import annotations

import argparse
import os
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import NamedTuple

KML_NS = "http://www.opengis.net/kml/2.2"
GX_NS = "http://www.google.com/kml/ext/2.2"
NS = {"k": KML_NS, "gx": GX_NS}


class Fix(NamedTuple):
    """One phone position. Ordered by time first, so ``sorted()`` does the right thing."""

    lat: float
    lon: float
    t: datetime

    def __lt__(self, other):
        return self.t < other.t


@dataclass
class Track:
    name: str
    fixes: list[Fix] = field(default_factory=list)


def _kml_text(path: str) -> str:
    path = os.path.expanduser(path)
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            names = [n for n in z.namelist() if n.lower().endswith(".kml")]
            if not names:
                raise ValueError(f"{path}: no .kml inside the archive")
            return z.read(names[0]).decode("utf-8", "replace")
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def _parse_when(text: str) -> datetime | None:
    text = (text or "").strip()
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def tracks(path: str) -> list[Track]:
    """Every `<gx:Track>` in the export, in file order, with its placemark's name."""
    root = ET.fromstring(_kml_text(path))
    out = []
    for pm in root.iter(f"{{{KML_NS}}}Placemark"):
        found = pm.findall(f".//{{{GX_NS}}}Track")
        if not found:
            continue
        name = (pm.findtext("k:name", default="", namespaces=NS) or "").strip()
        trk = Track(name=name)
        for gt in found:
            # A gx:Track is *not* interleaved: every <when> comes first, then every
            # <gx:coord>, so the two are paired by index. Walking the children in
            # document order and pairing each <when> with the next <gx:coord>
            # therefore yields exactly one fix per track, which reads like a nearly
            # empty export rather than a bug.
            whens = [_parse_when(w.text) for w in gt.findall("k:when", NS)]
            coords = [(c.text or "").split() for c in gt.findall("gx:coord", NS)]
            if len(whens) != len(coords):
                # Truncated export: keep the prefix, which is aligned, and drop the
                # tail rather than sliding every timestamp onto the wrong position.
                n = min(len(whens), len(coords))
                whens, coords = whens[:n], coords[:n]
            for when, parts in zip(whens, coords):
                if when is None or len(parts) < 2:
                    continue
                trk.fixes.append(Fix(float(parts[1]), float(parts[0]), when))
        out.append(trk)
    return out


AUTO = object()  # max_year default: take it from the file's own mtime


def load(path: str, max_year=AUTO, min_year: int = 2020) -> list[Fix]:
    """Every fix in the export, flattened, time-sorted, implausible years dropped.

    `max_year` defaults to the year the file was last written — a fix cannot postdate
    its own export, and the 2045 glitch is exactly that. Pass `None` to filter nothing.
    """
    if max_year is AUTO:
        try:
            max_year = datetime.fromtimestamp(
                os.path.getmtime(os.path.expanduser(path)), UTC
            ).year
        except OSError:
            max_year = None
    fixes = [f for t in tracks(path) for f in t.fixes]
    if max_year is not None:
        fixes = [f for f in fixes if min_year <= f.t.year <= max_year]
    return sorted(fixes)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("path", help="the .kmz or .kml export")
    ap.add_argument("--days", action="store_true", help="one line per UTC day")
    ap.add_argument("--from", dest="lo", help="first day (YYYY-MM-DD)")
    ap.add_argument("--to", dest="hi", help="last day")
    ap.add_argument("--all-years", action="store_true",
                    help="do not drop fixes dated after the export itself")
    a = ap.parse_args()

    fixes = load(a.path, max_year=None) if a.all_years else load(a.path)
    if a.lo or a.hi:
        fixes = [f for f in fixes
                 if (not a.lo or f.t.strftime("%Y-%m-%d") >= a.lo)
                 and (not a.hi or f.t.strftime("%Y-%m-%d") <= a.hi)]

    for t in tracks(a.path):
        if t.fixes:
            print(f"track {t.name!r}: {len(t.fixes)} fixes "
                  f"{t.fixes[0].t:%Y-%m-%dT%H:%MZ} .. {t.fixes[-1].t:%Y-%m-%dT%H:%MZ}")
    print(f"{len(fixes)} fixes after filtering")

    if a.days:
        from collections import Counter
        per = Counter(f.t.strftime("%Y-%m-%d") for f in fixes)
        for day in sorted(per):
            same = [f for f in fixes if f.t.strftime("%Y-%m-%d") == day]
            print(f"  {day}  {per[day]:6d} fixes  "
                  f"{same[0].t:%H:%M}..{same[-1].t:%H:%M}Z  "
                  f"lat {min(f.lat for f in same):.3f}..{max(f.lat for f in same):.3f}  "
                  f"lon {min(f.lon for f in same):.3f}..{max(f.lon for f in same):.3f}")


if __name__ == "__main__":
    main()
