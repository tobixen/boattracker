"""`boattracker` — the version, and an index of the tools.

Deliberately not a dispatcher. The journey tools each have their own substantial argparse
interface and their own docstring explaining the trap they exist to avoid, and wrapping
twenty of those behind subcommands would hide the `--help` that actually matters. Each is
run as a module:

    python -m boattracker.nfl.find_gaps --help
"""

import argparse

from . import __version__

TRACKER = [
    ("gpsparser", "the listening daemon; also installed as `boattracker-daemon`"),
    ("gt02a", "the TK103 wire format"),
    ("point", "geometry, stop and mooring detection"),
    ("alarm", "notifications, including the anchor alarm"),
]

NFL = [
    ("find_gaps", "the gap finder; four modes, `partial` is the one to trust"),
    ("find_backtracks", "backtracks and wrong fix order, six reports"),
    ("merge_leg", "one fix, one leg: merge every timed vertex for a leg into one track"),
    ("replace_tracker_chords", "replace a tracker straight line with plotter geometry"),
    ("track_dates", "date range per track, derived from nfl-export/ filenames"),
    ("tracker_archive", "the raw tracker feed, parsed into deduplicated days"),
    ("timestamp_segments", "date untimed plotter segments from timestamped phone fixes"),
    ("omaps_export", "the Organic Maps phone export as timestamped fixes"),
    ("exif_index", "photograph timestamp/GPS index"),
    ("photo_survey", "photographs against the track"),
    ("add_fixes", "backdated position fixes"),
    ("delete_fixes", "bulk deletion by fixId"),
    ("put_fix_path", "attach a path to an existing fix"),
    ("add_chapters", "hand-built journey chapters"),
    ("chapters_from_diary", "diary headings into journey chapters"),
    ("reimport_journey", "the live journey, exported to GPX"),
    ("prune_superseded_fixes", "hand-placed fixes that real track now covers"),
    ("dedupe_tracker_lines", "rebuild part-duplicated tracker lines"),
    ("rebuild_overlapping_fixes", "the same for hand-placed lines"),
    ("export_partial_runs", "fill a within-segment gap"),
    ("import_sdcard", "deduplicate a fresh SD-card export against the corpus"),
    ("crop_raymarine_track_to_gap", "crop a Raymarine track to a gap"),
    ("nfl_auth", "the API token: capture, store, decode, probe"),
    ("offset_track", "shift a line sideways, so an inbound leg does not sit on the outbound"),
    ("leg_export", "shared GPX and MIME builder used by the exporters"),
]


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="boattracker",
        description=__doc__.split("\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--version", "-V", action="version", version=f"%(prog)s {__version__}")
    ap.parse_args(argv)

    print(f"boattracker {__version__}\n")
    print("The daemon — python -m boattracker.tracker.<name>")
    for name, what in TRACKER:
        print(f"    {name:<28} {what}")
    print("\nThe journey tools — python -m boattracker.nfl.<name>")
    for name, what in NFL:
        print(f"    {name:<28} {what}")
    print("\nEvery one of them takes --help, and the docstring there is the real "
          "documentation.\nStart with IMPROVE-TRACKS.md for the order operations must happen in.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
