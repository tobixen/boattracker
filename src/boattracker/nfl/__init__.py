"""Tools for merging Raymarine chartplotter tracks with a noforeignland journey.

Start with `IMPROVE-TRACKS.md`, the runbook for the whole cycle, and the precedence rule
in `SOURCES.md`, which decides what belongs on the journey. Both are in the repository root.

These modules are written to be run: `python -m boattracker.nfl.find_gaps --help`.
The one-shot scripts that record how a particular past upload was built are not here and
not part of this package: they live in the journey record, `[paths] journey`/`historic/`,
because they document what was done to one boat rather than how to do it. They are not
expected to run.
"""
