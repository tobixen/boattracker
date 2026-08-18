"""Boat position tracking: a GPS/GSM tracker feed, and the tools that curate it.

Two halves, and they are used quite separately:

* `boattracker.tracker` — the daemon. It listens for a TK103-family GPS/GSM tracker,
  parses its wire format, detects sailing/stops/mooring/anchoring, and raises an anchor
  alarm when the boat leaves where it was left.
* `boattracker.nfl` — the journey tools. Merging Raymarine chartplotter geometry with the
  tracker's timestamps and keeping a noforeignland journey honest: finding gaps, finding
  backtracks, and uploading what is missing.

`boattracker.config` says where the data is and which boat it is; `boattracker.geo` is the
one haversine. Both are shared by the two halves.
"""

try:
    from ._version import __version__
except ImportError:  # pragma: no cover - a source tree with no build run yet
    __version__ = "0.0.0.dev0"

__all__ = ["__version__"]
