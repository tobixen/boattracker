"""Survey a stretch of days from the photograph index, ready for a hand-built track.

`exif_index.py --missing` answers "which days lack a position?". This answers the next
question — "what happened on this day, and could the boat have done it?" — which is the
one that matters for 2021, where the photographs are the primary source and there is no
chartplotter data at all (`journey/TRACKS-2021.md`).

Three things it does that reading the index by hand does not:

* **Collapses bursts.** Fifty-three photographs at a berth are one waypoint, not fifty-three
  track points. Positions within `--tol` metres of the previous one merge, but a *return*
  to an earlier spot stays separate, because going out and coming back is movement.
* **Checks implied speed between waypoints.** `IMPROVE-TRACKS.md` puts the plausible band
  at 0.4-9 kn. A photograph-derived chain breaches it more readily than any other source,
  because a car or a train may sit between two photographs — 2021-05-17 has Strömstad at
  09:31 and Gothenburg at 14:16, which is 50 nm at 10.6 kn and was the train.
* **Prints an openstreetmap link per waypoint**, and can throw the day's photographs at
  `feh`, so a position can be checked against what the picture actually shows.

Nothing here decides anything. A photograph places the photographer, not the boat; which
waypoints become track is the owner's judgement, recorded in `manual-locations.json`.

Times are EXIF local, printed exactly as stored — see `exif_index.py` on why they are never
converted. Norway and Sweden in summer are UTC+2, so subtract two hours before comparing
with the tracker's UTC fixes.
"""
import argparse
import json
import os
import re
import shlex
import subprocess
from dataclasses import dataclass, field
from datetime import datetime

from boattracker import config
from boattracker.geo import hav  # noqa: F401  -- re-exported under its original name

__getattr__ = config.lazy_module_getattr(
    'PHOTOS',
    ROOT=lambda: config.PHOTOS,
    INDEX=lambda: f'{config.PHOTOS}/exif-index.json',
    MANUAL=lambda: f'{config.PHOTOS}/manual-locations.json')

## argparse builds every argument before it can print --help, so a `const=WANT_DEFAULT_LOCATIONS` there
## would demand a configured photo archive just to read the usage text.
WANT_DEFAULT_LOCATIONS = ''
TAGS_DEFAULT = '/tmp/photo-survey-tags.tsv'
MIN_KN, MAX_KN = 0.4, 9.0

#: feh action keys, in order: Return, then 1, 2.
#:
#: `tag` means "look at this one". The other two are the judgement
#: `manual-locations.json` actually needs, and they are named after **the decision, not
#: after where the photographer was standing**: `ashore` is the file's own field, and
#: journey/TRACKS-2021.md defines it as "this position must never become boat track".
#:
#: So `boat` is not "taken from on deck". A photograph of the next berth's neighbour,
#: taken standing on the pontoon, is `boat` - the camera was metres from the hull and
#: the position is the boat's to within far less than a cell fix's error. The first
#: naming was `aboard`, which invited the physical reading and immediately produced the
#: question "it is neither ashore nor on the boat, but somewhere in the middle".
#: There is no middle for this purpose: either the position may be track, or it may not.
TAGS = ('tag', 'ashore', 'boat')




@dataclass
class Waypoint:
    lat: float
    lon: float
    first: str
    last: str
    n: int = 1
    paths: list = field(default_factory=list)
    recalled: bool = False
    ashore: bool = False
    note: str = ''
    fixes: set = field(default_factory=set)

    @property
    def cell_only(self):
        """True when no photograph here had a real GPS lock.

        `exif_index.py` stores GPSProcessingMethod as `fix`. `CELLID` is triangulated from
        cell towers and `network` from Wi-Fi and cell together.

        Neither is worthless, and it would be a mistake to discard them. Measured across
        this corpus against a GPS fix taken within two minutes:

            method    n     p50     p90      p95    under 1 km
            CELLID  1645    63 m   3051 m   5019 m     80%
            network  704   383 m   8863 m  19676 m     73%

        So a cell fix is usually **good** — a median of 63 m is better than the plotter's
        own point spacing. The problem is the tail: one in ten is kilometres out, and
        nothing in the file says which one. That is what put the boat at Fjällbacka on
        2021-05-17, 2.3 km from where the seamarks prove it was.

        The practical consequence is about *which question* the position may answer.
        Fine for choosing which day or leg a photograph belongs to, for confirming an area,
        and for matching a photograph against a real track to date it — a 63 m median beats
        anything else available for that. Coarser than one would want as a track coordinate
        on its own.

        **This tag is not a reliability filter, and must not be used as one.** `SOURCES.md`
        records the measurement: across 28 957 positions the *spike* rate is 0.07 % for
        `gps` against 0.04 % for `cellid` and `network`, so a GPS fix is if anything
        slightly likelier to be wildly wrong. Method bounds precision; it does not predict
        failure. Discarding cell fixes would throw away three quarters of the corpus to no
        benefit. Use the geometric tests — `repeats`, `wander`, implied speed — to find bad
        positions, and use this tag only to size the uncertainty on good ones.
        """
        return bool(self.fixes) and 'GPS' not in self.fixes


@dataclass
class Leg:
    a: Waypoint
    b: Waypoint
    nm: float
    hours: float
    kn: float

    @property
    def plausible(self):
        return MIN_KN <= self.kn <= MAX_KN


def in_range(rows, lo=None, hi=None):
    out = [r for r in rows if r.get('time')]
    if lo:
        out = [r for r in out if r['time'][:10] >= lo]
    if hi:
        out = [r for r in out if r['time'][:10] <= hi]
    return sorted(out, key=lambda r: (r['time'], r['path']))


def waypoints(rows, tol_m=50):
    """Consecutive positions within `tol_m` of the running waypoint become one waypoint.

    Compared against the waypoint being accumulated, not against every earlier one: a
    return to a place already visited is a separate stop, because the boat went somewhere
    and came back.
    """
    out = []
    for r in in_range(rows):
        if r.get('lat') is None:
            continue
        lat, lon = r['lat'], r['lon']
        if out and hav((out[-1].lat, out[-1].lon), (lat, lon)) <= tol_m:
            w = out[-1]
            w.last = r['time']
            w.n += 1
            w.paths.append(r['path'])
            if r.get('fix'):
                w.fixes.add(r['fix'])
            continue
        out.append(Waypoint(lat, lon, r['time'], r['time'], 1, [r['path']],
                            recalled=r.get('position_from') == 'recalled',
                            ashore=bool(r.get('ashore')), note=r.get('note', ''),
                            fixes={r['fix']} if r.get('fix') else set()))
    return out


def legs(wps):
    out = []
    for a, b in zip(wps, wps[1:]):
        nm = hav((a.lat, a.lon), (b.lat, b.lon)) / 1852
        dt = datetime.fromisoformat(b.first) - datetime.fromisoformat(a.last)
        hours = dt.total_seconds() / 3600
        kn = nm / hours if hours > 0 else float('inf')
        out.append(Leg(a, b, nm, hours, kn))
    return out


def repeats(wps, places=5):
    """Positions served more than once non-consecutively, with the span they cover.

    The single strongest indicator that a phone is handing back a cached or
    network-derived fix rather than a GPS one. `waypoints` has already merged
    *consecutive* photographs at one spot, so a position appearing in two or more
    waypoints means the phone left it and came back to it **exactly** — to five
    decimal places, roughly a metre. A boat under way cannot do that; on 2021-05-18
    one position was served eight times across 65 minutes.

    Returns [((lat, lon), n_waypoints, span_seconds)], longest span first.
    """
    from collections import defaultdict
    seen = defaultdict(list)
    for w in wps:
        seen[(round(w.lat, places), round(w.lon, places))].append(w)
    out = []
    for pos, group in seen.items():
        if len(group) < 2:
            continue
        span = (datetime.fromisoformat(group[-1].last)
                - datetime.fromisoformat(group[0].first)).total_seconds()
        out.append((pos, len(group), span))
    return sorted(out, key=lambda t: -t[2])


def wander(wps):
    """Path length divided by net displacement. ~1 for a passage, large for scatter."""
    if len(wps) < 2:
        return 0.0
    path = sum(hav((a.lat, a.lon), (b.lat, b.lon)) for a, b in zip(wps, wps[1:]))
    net = hav((wps[0].lat, wps[0].lon), (wps[-1].lat, wps[-1].lon))
    if net < 1.0:                     # returned to within a metre of the start
        return float('inf') if path > 1.0 else 0.0
    return path / net


def median_position(wps):
    """Median latitude and longitude — robust to the outliers scatter produces.

    A mean is dragged toward whichever wild fix the phone invented; on 2021-05-18 one
    position sits 6 nm from the rest and would shift a mean by a third of a mile.
    """
    la = sorted(w.lat for w in wps)
    lo = sorted(w.lon for w in wps)
    mid = lambda v: (v[len(v)//2] if len(v) % 2
                     else (v[len(v)//2 - 1] + v[len(v)//2]) / 2)
    return mid(la), mid(lo)


def is_scatter(wps, wander_limit=5.0):
    return bool(repeats(wps)) and wander(wps) > wander_limit


def classify(wps):
    """('moving' | 'stationary' | 'stationary-scattered' | 'unclear', reasons).

    Deliberately **not** biased toward `stationary`. A burst of photographs is not
    evidence of standing still: sunset shots taken from a boat under way carry real
    speed and direction, and throwing them away would discard exactly the information
    this project exists to recover. So `moving` is returned whenever the positions
    advance in order at a plausible speed, and scatter has to be positively shown —
    by an exactly-repeated position, or by a path far longer than the displacement.
    """
    reasons = []
    if len(wps) < 2:
        return 'stationary', ['only one position']
    lg = legs(wps)
    bad = [e for e in lg if not e.plausible]
    rp = repeats(wps)
    w = wander(wps)
    if rp:
        pos, n, span = rp[0]
        reasons.append(f'{pos[0]:.5f},{pos[1]:.5f} served {n}x across {span/60:.0f} min '
                       '- a boat cannot return to a position exactly')
    if w > 5:
        reasons.append(f'path is {w:.0f}x the net displacement')
    if bad:
        reasons.append(f'{len(bad)} of {len(lg)} legs outside {MIN_KN}-{MAX_KN} kn')
    if rp and w > 5:
        return 'stationary-scattered', reasons
    if not bad and w < 2:
        return 'moving', [f'positions advance in order, path {w:.2f}x displacement']
    return 'unclear', reasons or ['no clear signal either way']


def osm_link(lat, lon, zoom=13):
    return (f'https://www.openstreetmap.org/?mlat={lat:.5f}&mlon={lon:.5f}'
            f'#map={zoom}/{lat:.5f}/{lon:.5f}')


def bbox_link(wps, pad=0.02):
    la = [w.lat for w in wps]
    lo = [w.lon for w in wps]
    return ('https://www.openstreetmap.org/?bbox='
            f'{min(lo)-pad:.5f},{min(la)-pad:.5f},{max(lo)+pad:.5f},{max(la)+pad:.5f}')


def feh_command(files, tag_file, notify=True):
    """The viewer, wired so that what the owner picks out survives the window closing.

    `--draw-filename` puts the name on the image and `--draw-actions` the key list, so
    neither has to be memorised. Each key appends one tab-separated line to `tag_file`:
    timestamp, label, path.

    Each action then fires a desktop notification, because the `;` flag below repaints
    the *same* image and a successful tag is otherwise indistinguishable from a dead
    key - the first use of this ended with one photograph tagged nine times. The
    notification runs **after** the append and is separated by `;` rather than `&&`, so
    a missing or broken notifier cannot cost a tag. `notify=False` is for the test that
    executes the command for real and should not put anything on the desktop.

    Two escaping traps, both load-bearing:

    * **`%s` is a feh specifier**, not printf's — it expands to the image size in bytes
      before `/bin/sh` sees the command. `%%` is feh's literal percent, so the format
      string has to be written `%%s` here to arrive as `%s`.
    * **`%F`, not `%f`** — only `%F` is shell-escaped, and photograph names contain
      spaces.
    * **The format string is quoted for `/bin/sh`** — unquoted, the shell strips the
      backslashes and printf receives ` t` where the tabs should be, so the columns run
      together on exactly the paths that need splitting.

    The leading `;` keeps feh on the current image after the action instead of advancing,
    which is what makes tagging two labels onto one photograph possible.
    """
    out = ['feh', '--scale-down', '--auto-zoom', '--draw-filename', '--draw-actions',
           '--sort', 'filename']
    dest = shlex.quote(tag_file)
    for i, label in enumerate(TAGS):
        flag = '--action' if i == 0 else f'--action{i}'
        note = (f'; notify-send -t 900 '
                f'-h string:x-canonical-private-synchronous:photo-survey '
                f'{label} %N') if notify else ''
        out += [flag, f";[{label}]printf '%%s\\t%%s\\t%%s\\n' "
                      f'"$(date -Is)" {label} %F >> {dest}{note}']
    return out + list(files)


def read_tags(path):
    """Read back what the owner tagged: [{'time', 'label', 'path'}], in tagging order.

    Paths under `ROOT` come back relative, because that is how `exif-index.json` keys
    them and the whole point of a tag is to find the photograph's row again.
    """
    out = []
    try:
        with open(path) as f:
            lines = f.readlines()
    except FileNotFoundError:
        return out
    for line in lines:
        parts = line.rstrip('\n').split('\t')
        if len(parts) != 3:
            continue
        when, label, p = parts
        out.append({'time': when, 'label': label,
                    'path': os.path.relpath(p, config.PHOTOS) if p.startswith(config.PHOTOS + '/') else p})
    return out


def apply_overlay(rows, path):
    """Merge the owner's recall using `exif_index`'s own implementation.

    Deliberately delegated rather than reimplemented. This module used to carry its own
    copy, written when the overlay could only fill missing positions, and it silently
    diverged once `drop` and `override` were added: eight corrected 2021-05-17
    photographs still reported their false Fjällbacka positions here while
    `exif_index.py` reported them correctly. One file, one merge, one answer.
    """
    from boattracker.nfl import exif_index
    have = {r['path']: r for r in rows}
    return list(exif_index.apply_manual(have, path).values())


def load(locations=None):
    with open(f'{config.PHOTOS}/exif-index.json') as f:
        rows = json.load(f)
    if locations:
        rows = apply_overlay(rows, locations)
    return rows


def report(rows, tol_m, show_paths):
    by_day = {}
    for r in rows:
        by_day.setdefault(r['time'][:10], []).append(r)
    for day in sorted(by_day):
        drows = by_day[day]
        nogps = [r for r in drows if r.get('lat') is None]
        wps = waypoints(drows, tol_m)
        print(f'\n=== {day}   {len(drows)} photographs, {len(wps)} waypoints'
              + (f', {len(nogps)} without position' if nogps else '') + ' ===')
        if not wps:
            dirs = sorted({os.path.dirname(r['path']) or '.' for r in drows})
            print(f'    no position at all - directories: {", ".join(dirs)}')
            continue
        lg = legs(wps)
        for i, w in enumerate(wps):
            span = f'{w.first[11:16]}' + (f'-{w.last[11:16]}' if w.last != w.first else '     ')
            tags = ''.join([' [recalled]' if w.recalled else '',
                            ' [ASHORE]' if w.ashore else '',
                            ' [CELL]' if w.cell_only else ''])
            print(f'  {span}  {w.lat:9.5f},{w.lon:9.5f}  n={w.n:<3d}{tags}  {osm_link(w.lat, w.lon)}')
            if w.note:
                print(f'                 note: {w.note}')
            if show_paths:
                for p in w.paths:
                    print(f'                 {p}')
            if i < len(lg):
                e = lg[i]
                mark = '   ' if e.plausible else ' !!'
                kn = 'inf' if e.kn == float('inf') else f'{e.kn:.1f}'
                print(f'      {mark} {e.nm:6.2f} nm  {e.hours:5.2f} h  {kn:>5s} kn')
        print(f'  overview: {bbox_link(wps)}')
        verdict, reasons = classify(wps)
        print(f'  verdict: {verdict.upper()}')
        for r in reasons:
            print(f'     - {r}')
        if verdict == 'stationary-scattered':
            la, lo = median_position(wps)
            print(f'     median position {la:.5f},{lo:.5f}  {osm_link(la, lo)}')
            print('     (use one waypoint for this day; the spread is the phone, not the boat)')


_DM = re.compile(r"""(\d{1,3})\s*[º°o]\s*(\d{1,2}(?:\.\d+)?)\s*'?\s*""", re.X)


def parse_position(text):
    """(lat, lon) from either decimal degrees or the owner's degrees-and-minutes.

    He types positions the way a chart plotter shows them - `059º53.269' N /
    010º35.363' E` - and every one of those was being converted by hand into a throwaway
    script. Copy-paste turns `º` into `°` or a plain `o`, the slash is not always present,
    and the hemisphere letter may lead or follow, so all of that is accepted.

    Raises ValueError rather than guessing: a half-parsed position is worse than none,
    because it looks like a measurement.
    """
    if not isinstance(text, str) or not text.strip():
        raise ValueError('no position given')
    s = text.strip()
    dm = _DM.findall(s)
    if len(dm) >= 2:
        vals = [int(d) + float(m) / 60 for d, m in dm[:2]]
        hemis = re.findall(r'[NSEWnsew]', s)
        if any(h in 'Ss' for h in hemis[:1]):
            vals[0] = -vals[0]
        if len(hemis) > 1 and hemis[1] in 'Ww':
            vals[1] = -vals[1]
        lat, lon = vals
    else:
        parts = [x for x in re.split(r'[,;\s]+', s) if x]
        if len(parts) != 2:
            raise ValueError(f'cannot read a position from {text!r}')
        try:
            lat, lon = float(parts[0]), float(parts[1])
        except ValueError:
            raise ValueError(f'cannot read a position from {text!r}') from None
    if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        raise ValueError(f'{lat},{lon} is out of range for a position')
    return lat, lon


def distances_to(wps, position):
    """[(waypoint, metres)] against a candidate position, nearest first.

    The central move of the 2021 method (`journey/TRACKS-2021.md`): ask the owner, then see which
    fix agrees. What makes it work is that the answer is usually **one** fix close and the
    rest miles off - Lilla Kornö 50 m, Hogö 58 m, Akerøy 37 m - because the majority fix is
    the cell tower, not the boat. So the ranking matters more than any average.
    """
    return sorted(((w, hav((w.lat, w.lon), position)) for w in wps), key=lambda t: t[1])


def current_tags(tagged):
    """{path: label} keeping only the **last** label given to each photograph.

    Re-pressing a key is how a mistake is corrected, so the newest keypress wins and a
    photograph is never both `ashore` and `boat`. `read_tags` still returns the whole
    log; this is the view that answers "what does the owner say about this picture now".
    """
    return {t['path']: t['label'] for t in tagged}


def report_tags(tag_file, rows):
    """What the owner picked out, back in the same terms as the survey.

    Each tagged photograph reappears with its EXIF time, its indexed position and a map
    link, so a tag made in the viewer can be turned into a `manual-locations.json` entry
    without hunting for the file again. A photograph with no position of its own still
    lists - those are often the interesting ones, since a tag is the only thing placing
    them.
    """
    tagged = read_tags(tag_file)
    if not tagged:
        print(f'nothing tagged in {tag_file}')
        return
    have = {r['path']: r for r in rows}
    now = current_tags(tagged)
    changed = {t['path'] for t in tagged if t['label'] != now[t['path']]}
    print(f'{len(tagged)} keypresses on {len(now)} photographs in {tag_file}'
          + (f', {len(changed)} corrected' if changed else ''))
    for path, label in sorted(now.items(), key=lambda kv: have.get(kv[0], {}).get('time', '')):
        mark = ' (corrected)' if path in changed else ''
        r = have.get(path)
        if r is None:
            print(f'  {label:<7s} {path}   (outside the surveyed days){mark}')
            continue
        where = (f"{r['lat']:9.5f},{r['lon']:9.5f}  {osm_link(r['lat'], r['lon'])}"
                 if r.get('lat') is not None else 'no position')
        print(f"  {label:<7s} {r['time'][:16]}  {where}{mark}")
        print(f'          {path}')


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--from', dest='lo', required=True, help='first day (YYYY-MM-DD)')
    ap.add_argument('--to', dest='hi', help='last day (default: same as --from)')
    ap.add_argument('--tol', type=float, default=50,
                    help='metres within which consecutive photographs are one place')
    ap.add_argument('--paths', action='store_true', help='list every file under its waypoint')
    ap.add_argument('--locations', nargs='?', const=WANT_DEFAULT_LOCATIONS, default=None,
                    help='merge remembered positions (default: %(const)s)')
    ap.add_argument('--feh', action='store_true', help='open the photographs in feh')
    ap.add_argument('--tags', default=TAGS_DEFAULT,
                    help='file the feh tag keys append to (default: %(default)s)')
    ap.add_argument('--read-tags', action='store_true',
                    help='print what was tagged, with each photograph\'s position, and exit')
    ap.add_argument('--near', metavar='POS',
                    help="rank each day's waypoints by distance to a remembered position; "
                         "takes 59.8878,10.5894 or \"059º53.269' N / 010º35.363' E\"")
    ap.add_argument('--map', action='store_true',
                    help="open the day's median position in the browser")
    a = ap.parse_args()
    if a.locations == WANT_DEFAULT_LOCATIONS:
        a.locations = f'{config.PHOTOS}/manual-locations.json'
    hi = a.hi or a.lo
    rows = in_range(load(a.locations), a.lo, hi)
    if not rows:
        print(f'no photographs indexed for {a.lo}..{hi}')
        return
    if a.read_tags:
        report_tags(a.tags, rows)
        return
    if a.near:
        pos = parse_position(a.near)
        print(f'candidate {pos[0]:.6f}, {pos[1]:.6f}   {osm_link(*pos)}\n')
        by_day = {}
        for r in rows:
            by_day.setdefault(r['time'][:10], []).append(r)
        for day in sorted(by_day):
            wps = waypoints([r for r in by_day[day] if r.get('lat') is not None], a.tol)
            nopos = [r for r in by_day[day] if r.get('lat') is None]
            print(f'=== {day} ===')
            for w, d in distances_to(wps, pos):
                tags = ' [ASHORE]' if w.ashore else (' [CELL]' if w.cell_only else '')
                print(f'  {d:8.0f} m  {w.first[11:16]}  {w.lat:9.5f},{w.lon:9.5f} '
                      f' n={w.n:<3d}{tags}')
            if nopos:
                print(f'  {len(nopos)} photograph(s) with no position of their own: '
                      + ', '.join(os.path.basename(r['path']) for r in nopos))
        return
    report(rows, a.tol, a.paths)
    if a.feh:
        files = [os.path.join(config.PHOTOS, r['path']) for r in rows]
        print(f'\nfeh: {len(files)} files, tagging to {a.tags}')
        print('      Return = tag, 1 = ashore, 2 = boat;'
              f' read back with --read-tags --tags {a.tags}')
        subprocess.Popen(feh_command(files, a.tags))
    if a.map:
        wps = waypoints([r for r in rows if not r.get('ashore')], a.tol)
        if not wps:
            print('no position to map')
            return
        la, lo = median_position(wps)
        url = osm_link(la, lo, zoom=16)
        print(f'\nmap: {url}')
        subprocess.Popen(['xdg-open', url],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == '__main__':
    main()
