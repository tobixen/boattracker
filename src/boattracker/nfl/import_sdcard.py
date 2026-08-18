#!/usr/bin/env python3
"""Copy Raymarine GPX exports off the plotter's SD card and report what is new.

Deduplicates at track level using raymarine:GUID, which is stable across exports:
the same track re-exported keeps its GUID, so a GUID already held locally is a
duplicate however the file has been renamed or re-cut.

Usage:  import_sdcard.py [--card DIR] [--dest DIR] [--copy]

Without --copy it only reports.  The card is normally mounted by
    udisksctl mount -b /dev/sda1
which lands it under /run/media/$USER/<LABEL>.
"""
import argparse
import glob
import hashlib
import os
import re
import shutil
import sys

from boattracker import config, files

GUID = re.compile(r'<raymarine:GUID>(.*?)</raymarine:GUID>', re.S)
NAME = re.compile(r'<name>(.*?)</name>', re.S)
TRK = re.compile(r'<trk>.*?</trk>', re.S)
PT = re.compile(r'<trkpt\b')


def tracks(path):
    """{guid: (name, point count)} for one GPX file"""
    out = {}
    txt = files.read_text(path, errors='replace')
    for trk in TRK.findall(txt):
        g = GUID.search(trk)
        n = NAME.search(trk)
        if g:
            out[g.group(1).strip()] = (n.group(1).strip() if n else '?',
                                       len(PT.findall(trk)))
    return out


def md5(path):
    h = hashlib.md5()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--card', default=None,
                    help='card mount point; autodetected under /run/media/$USER if omitted')
    ap.add_argument('--dest', default=config.DATA,
                    help='where the local corpus lives')
    ap.add_argument('--copy', action='store_true', help='actually copy the new files')
    a = ap.parse_args()

    card = a.card
    if not card:
        cands = glob.glob(f'/run/media/{os.environ.get("USER","tobias")}/*/Raymarine/My Data')
        if not cands:
            sys.exit('no card found; mount it with: udisksctl mount -b /dev/sda1')
        card = cands[0]
    print(f'card:  {card}')
    print(f'local: {a.dest}')

    local_files = sorted(glob.glob(f'{a.dest}/*.gpx'))
    local = {}
    for f in local_files:
        for g, v in tracks(f).items():
            local.setdefault(g, (v[0], v[1], os.path.basename(f)))
    print(f'\nlocal corpus: {len(local_files)} files, {len(local)} distinct track GUIDs')

    local_md5 = {md5(f) for f in local_files}
    card_files = sorted(glob.glob(f'{card}/*.gpx'))
    print(f'card: {len(card_files)} files\n')

    to_copy, new_tracks = [], {}
    for f in card_files:
        t = tracks(f)
        fresh = {g: v for g, v in t.items() if g not in local}
        same = md5(f) in local_md5
        state = 'identical to a local file' if same else \
                (f'{len(fresh)} NEW tracks' if fresh else 'all tracks already held')
        print(f'  {os.path.basename(f):24s} {os.path.getsize(f):>10d} B  '
              f'{len(t):3d} tracks  {state}')
        for g, v in sorted(fresh.items(), key=lambda kv: kv[0]):
            print(f'        NEW  {g}  {v[0]:18s} {v[1]:6d} pts')
            new_tracks[g] = (v[0], v[1], os.path.basename(f))
        if fresh:
            to_copy.append(f)

    print(f'\n{len(new_tracks)} new tracks in {len(to_copy)} file(s)')
    if not to_copy:
        return
    for f in to_copy:
        dst = os.path.join(a.dest, os.path.basename(f))
        if a.copy:
            shutil.copy2(f, dst)
            print(f'  copied {os.path.basename(f)} -> {dst}')
        else:
            print(f'  would copy {os.path.basename(f)} -> {dst}   (pass --copy)')


if __name__ == '__main__':
    main()
