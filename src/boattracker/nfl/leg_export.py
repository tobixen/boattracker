"""Shared builder for noforeignland leg uploads.

`export_july2026.py`, `export_march2025_gaps.py` and `split_aug2025_bridge.py` each grew
their own copy of the same GPX-and-MIME construction. This is that logic in one place; new
exports should use it, and the three older scripts should migrate to it when next touched
(their leg tables are what matter and are worth keeping verbatim, so they have deliberately
not been rewritten while their uploads are the record of what was sent).

What the importer needs, and what is easy to get wrong:

* One GPX becomes exactly **one fix**, timestamped at the **last** point. Splitting a
  passage into per-day legs is therefore the only way to get per-day timestamps.
* A new fix within a few metres of an existing one is **merged silently**. Delete the old
  fix first; re-sending on its own is a no-op.
* The `creator` attribute drives the source label shown on the journey, so anything that is
  not chartplotter geometry must say so there.
"""
import os
import re
import xml.etree.ElementTree as ET
from datetime import timedelta
from email.message import EmailMessage

from boattracker import config, files
from boattracker.geo import hav  # noqa: F401  -- re-exported; callers do `LE.hav` and `from leg_export import hav`

__getattr__ = config.lazy_module_getattr('FROM')
TO = config.TO
GPXDIR = config.GPXDIR
T = config.DATA

RAYMARINE_CREATOR = 'raymarine track, dated from the ship diary and engine log'

_dpat = re.compile(r'<trkpt lon="([^"]+)" lat="([^"]+)"(?:\s*/>|>(.*?)</trkpt>)', re.S)
_cache = {}

def segment(gpx_file, track_name, seg_index, bbox=(35.0, 44.5, 23.0, 30.5)):
    """Raymarine segment as [(lat, lon, extensions_blob)], junk positions filtered out.

    Segments are split on the **opening** tag, not on a closing one. `benelux.gpx` and
    the since-deleted `france.gpx` carry a `<trkseg>` that is never closed (`../SOURCES.md`), and
    matching `<trkseg>.*?</trkseg>` silently drops it — merging it into its neighbour and
    shifting every index after it onto the wrong water. Nothing raises; the export just
    describes a different passage. Splitting on the opener keeps indices stable whether or
    not the file is well formed.

    `gpx_file` may be absolute, in which case the repository root is not prepended.
    """
    if gpx_file not in _cache:
        with open(os.path.join(T, gpx_file), errors='replace') as f:
            txt = f.read()
        _cache[gpx_file] = {re.search(r'<name>(.*?)</name>', t).group(1):
                            re.findall(r'<trkseg>.*?(?=<trkseg>|</trk>|\Z)', t, re.S)
                            for t in re.findall(r'<trk>.*?(?=<trk>|\Z)', txt, re.S)}
    raw = _cache[gpx_file][track_name][seg_index]
    la0, la1, lo0, lo1 = bbox
    return [(float(la), float(lo), b) for lo, la, b in _dpat.findall(raw)
            if la0 < float(la) < la1 and lo0 < float(lo) < lo1]

def _head(creator):
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<gpx version="1.1" creator="{creator}"\n'
            '     xmlns="http://www.topografix.com/GPX/1/1"\n'
            '     xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"\n'
            '     xmlns:raymarine="http://www.raymarine.com"\n'
            '     xsi:schemaLocation="http://www.topografix.com/GPX/1/1 '
            'http://www.topografix.com/GPX/1/1/gpx.xsd">\n')

_iso = lambda t: t.strftime('%Y-%m-%dT%H:%M:%SZ')

def build(points, name, desc, t0, t1, filename, creator=RAYMARINE_CREATOR,
          min_spacing_m=30, outbox=None, write_gpx=True):
    """Timestamp `points` across [t0, t1] by cumulative distance and write GPX + .eml.

    Returns (path_nm, kept_points, implied_kn). Raises if the GPX does not parse — nothing
    unparseable should ever reach the importer.
    """
    cum = [0.0]
    for i in range(1, len(points)):
        cum.append(cum[-1] + hav(points[i-1], points[i]))
    total = cum[-1] or 1.0
    span = (t1-t0).total_seconds()
    body = [_head(creator), ' <metadata>\n', f'  <name>{name}</name>\n',
            f'  <desc>{desc}</desc>\n', f'  <time>{_iso(t1)}</time>\n',
            ' </metadata>\n', ' <trk>\n', f'  <name>{name}</name>\n', '  <trkseg>\n']
    kept, last = 0, None
    for i, pt in enumerate(points):
        if last is not None and cum[i]-last < min_spacing_m and i != len(points)-1:
            continue
        last = cum[i]; kept += 1
        la, lo = pt[0], pt[1]
        extra = pt[2] if len(pt) > 2 else None
        ts = t0 + timedelta(seconds=span*cum[i]/total)
        line = f'   <trkpt lat="{la}" lon="{lo}"><time>{_iso(ts)}</time>'
        m = re.search(r'<raymarine:WaterDepth>([^<]+)</', extra or '')
        if m:
            line += ('<extensions><raymarine:WaterDepth>' + m.group(1)
                     + '</raymarine:WaterDepth></extensions>')
        body.append(line + '</trkpt>\n')
    body += ['  </trkseg>\n', ' </trk>\n', '</gpx>\n']
    gpx = ''.join(body)
    ET.fromstring(gpx)
    if write_gpx:
        files.write_text(f'{GPXDIR}/{filename}', gpx)
    if outbox:
        os.makedirs(outbox, exist_ok=True)
        msg = EmailMessage()
        msg['From'] = config.FROM; msg['To'] = TO
        msg['Subject'] = config.subject(name)
        msg.set_content(f'Track for S/Y {config.BOAT_NAME}: {name}\n\n{kept} points, {_iso(t0)} to '
                        f'{_iso(t1)}, {total/1852:.2f} nm.\n\n{desc}\n')
        msg.add_attachment(gpx.encode(), maintype='application', subtype='gpx+xml',
                           filename=filename)
        open(f"{outbox}/{filename.replace('.gpx', '.eml')}", 'wb').write(bytes(msg))
    hrs = span/3600
    return total/1852, kept, (total/1852/hrs if hrs > 0 else 0.0)
