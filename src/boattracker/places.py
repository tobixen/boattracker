"""Named places from PLACES.md, and the timezone at a position.

PLACES.md is the owner's table of named spots (the `journey/` record's naming authority);
`time_and_positions` names the diary's stops from it, and other tools look a place's
position up by name.
"""

from __future__ import annotations

import re

LatLon = tuple[float, float]


## Reserved names in PLACES.md for spots that are not places: the owner's verdict that a
## "stop" there was slow sailing, or that a position there was the phone carried ashore.
AT_SEA = 'at sea'
ASHORE = 'ashore (not the boat)'


def read_places(path: str) -> tuple[list[tuple[str, float, float]], list[LatLon], list[LatLon]]:
    """(places, at_sea, ashore) from a PLACES.md table: named places as (name, lat, lon),
    and the positions of the two reserved names as (lat, lon)."""
    places, at_sea, ashore = [], [], []
    with open(path) as f:
        for line in f:
            m = re.match(r'\|\s*([^|]+?)\s*\|\s*(-?\d+\.\d+)\s*\|\s*(-?\d+\.\d+)\s*\|', line)
            if not m:
                continue
            name, pos = m.group(1), (float(m.group(2)), float(m.group(3)))
            if name == AT_SEA:
                at_sea.append(pos)
            elif name == ASHORE:
                ashore.append(pos)
            else:
                places.append((name, *pos))
    return places, at_sea, ashore


def zone_at(lat: float, lon: float) -> str | None:
    """The zone at a position, or None offshore, where only the nautical zones exist."""
    try:
        from tzfpy import get_tz
    except ImportError as e:
        raise SystemExit('the timezone at a position needs tzfpy: pip install "boattracker[diary]"') from e
    z = get_tz(lon, lat)
    return None if not z or z.startswith('Etc/') else z
