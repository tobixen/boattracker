# Getting Organic Maps tracks and bookmarks onto the laptop

## Why the app directory cannot be synced directly

Organic Maps stores bookmark categories and recorded tracks under

    /sdcard/Android/data/app.organicmaps/files/bookmarks/

Since Android 11 no ordinary app may read another app's `Android/data`
subtree.  The `MANAGE_EXTERNAL_STORAGE` permission ("All files access")
explicitly excludes `Android/data` and `Android/obb`, so neither Syncthing nor
Syncthing-Fork can be pointed at that directory, with or without extra
permissions.  Only the `shell` uid (via adb) or root can reach it.

Rooting was considered and rejected: unlocking a Xiaomi bootloader under
HyperOS requires a Mi account at least 30 days old, one unlock per account per
year, a knowledge quiz, 3-7 days of waiting, a full data wipe, and it stops OTA
updates.

## What to do with the export once it has arrived

    python3 -m boattracker.nfl.import_phone_export --write --commit

`import_phone_export.py` takes the newest `.kmz` in each of the two mirrors below, unpacks
the single `.kml` inside it, and installs it as `<data>/../phone/<phone>.kml` — a git
repository of its own, committed one export at a time, one file per phone since each phone
records its own track. Once the commit is made the `.kmz` can be deleted from the mirror,
which tidies the phone too; the tool says when.

Three things that module's docstring explains and this file should not repeat: the KML is
committed rather than the KMZ, because a zip cannot be delta-compressed and is not even
reproducible; the export is append-only and already one fix per line, so nothing is
reformatted; and a new export that has **lost** recorded positions is refused rather than
installed, because the committed copy is then the better one.

The repository is deliberately **not** part of `~/solveig`: that working tree is served on
the open web, and the phone's track is a person's movements rather than the boat's. See
`tracks/phone/README.md` in the corpus.

## Current setup: export button + receive-only Syncthing folders

In Organic Maps: Bookmarks -> the three-dot menu -> Export KMZ / GPX / GeoJSON.
The default save location is the phone's `Download/` folder.

Two Syncthing folders on the laptop mirror those directories:

| folder id          | laptop path         | phone                          |
|--------------------|---------------------|--------------------------------|
| `pixel8-downloads` | `~/Downloads/pixel` | pixel8 (`JUKMJYB`)             |
| `newmi-downloads`  | `~/Downloads/newmi` | RedMi-Phone (`WFCMTTG`), Redmi 13C |

These are deliberately *not* git-tracked, unlike `~/solveig` and
`~/s/syncthing/data`, which use the `syncthing-git` versioning hook.

Both sides are send-receive, so the phone's `Download/` folder can be tidied up
from the laptop.  That also means a laptop-side deletion really deletes on the
phone, whatever the file was; trashcan versioning on the phone side is the
safety net for that.

To sync only map data instead of the whole Downloads junk drawer, put this in
`.stignore` in the laptop-side folder:

    !*.kmz
    !*.kml
    !*.gpx
    !*.geojson
    *

Ignore patterns are per-device, and an ignored directory is not descended into,
so this only works for files sitting directly in `Download/`.

## Alternative: pull the raw directory over adb

The adb daemon on the phone runs as uid 2000 (`shell`), which is not subject to
the scoped-storage restriction above.  With USB debugging enabled:

    adb pull /sdcard/Android/data/app.organicmaps/files/bookmarks/ ./bookmarks/

This captures the app's own files rather than manual exports, including
deletions, and can be driven from a systemd timer.  Costs: USB debugging has to
stay enabled, and `adb tcpip 5555` / wireless debugging must be set up for it to
work without a cable.  Some MIUI/HyperOS builds restrict adb's access to
`Android/data` as well, so verify with `adb shell ls` before relying on it.
