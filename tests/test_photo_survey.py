"""Tests for the photograph survey helper.

The two things worth pinning down are the ones that decide whether a photograph-derived
chain is honest:

* collapsing a burst of photographs taken from one spot into **one** waypoint, so a day
  with 53 photographs at a berth does not become 53 track points; and
* the implied-speed check, which is what catches a car journey or a train ride hiding
  between two photographs. `IMPROVE-TRACKS.md` puts the plausible band at 0.4-9 kn, and
  the 2021 material is the most likely of all sources to breach it.
"""

import pytest

from boattracker.nfl import photo_survey as p


def rec(time, lat=None, lon=None, path='x.jpg', **kw):
    return dict(path=path, time=time, lat=lat, lon=lon, model='test', **kw)


def test_waypoints_collapse_a_burst_taken_from_one_spot():
    rows = [rec('2021-05-13T13:46:24', 59.85815, 10.55266),
            rec('2021-05-13T13:46:24', 59.85815, 10.55266),
            rec('2021-05-13T13:49:12', 59.85815, 10.55266),
            rec('2021-05-13T13:54:16', 59.85626, 10.54892)]
    wps = p.waypoints(rows, tol_m=50)
    assert len(wps) == 2
    assert wps[0].n == 3
    assert wps[0].first == '2021-05-13T13:46:24'
    assert wps[0].last == '2021-05-13T13:49:12'
    assert wps[1].n == 1


def test_waypoints_keep_a_return_to_an_earlier_spot_as_its_own_stop():
    # 2021-05-17 really does go out and come back; that is movement, not one place.
    rows = [rec('2021-05-17T18:56:06', 58.55451, 11.27337),
            rec('2021-05-17T19:08:51', 58.59816, 11.28727),
            rec('2021-05-17T20:21:25', 58.55451, 11.27337)]
    assert [w.n for w in p.waypoints(rows, tol_m=50)] == [1, 1, 1]


def test_waypoints_ignore_photographs_with_no_position():
    rows = [rec('2021-05-18T21:11:11', None, None),
            rec('2021-05-18T21:11:11', 58.30593, 11.42128)]
    assert len(p.waypoints(rows, tol_m=50)) == 1


def test_legs_flag_an_impossible_speed():
    # Strömstad 09:31 to Gothenburg 14:16 is ~50 nm in under 5 h: a train, not the boat.
    wps = p.waypoints([rec('2021-05-17T09:31:01', 58.93891, 11.17589),
                       rec('2021-05-17T14:16:35', 57.70359, 11.96965)], tol_m=50)
    leg, = p.legs(wps)
    assert leg.kn > 9
    assert not leg.plausible


def test_legs_accept_an_ordinary_sailing_speed():
    wps = p.waypoints([rec('2021-05-17T15:45:59', 58.69470, 11.17204),
                       rec('2021-05-17T16:57:28', 58.62931, 11.33593)], tol_m=50)
    leg, = p.legs(wps)
    assert 0.4 <= leg.kn <= 9
    assert leg.plausible


def test_legs_do_not_divide_by_zero_when_two_photographs_share_a_second():
    wps = p.waypoints([rec('2021-05-19T12:44:48', 58.41360, 11.47307),
                       rec('2021-05-19T12:44:48', 58.30621, 11.36711)], tol_m=50)
    leg, = p.legs(wps)
    assert leg.kn == float('inf')
    assert not leg.plausible


def test_osm_link_marks_the_position():
    url = p.osm_link(58.93891, 11.17589)
    assert 'mlat=58.93891' in url and 'mlon=11.17589' in url and '#map=' in url


def test_a_moving_boat_is_classified_as_moving_even_from_a_photo_burst():
    """A burst of photographs is NOT evidence of standing still.

    Sunset shots from a boat under way carry real speed and direction, and the
    classifier must return them rather than average them away. This is the case that
    stops `stationary` from being the lazy default.
    """
    rows = [rec('2021-05-21T21:00:00', 57.9500, 11.5000),
            rec('2021-05-21T21:10:00', 57.9600, 11.5200),
            rec('2021-05-21T21:20:00', 57.9700, 11.5400),
            rec('2021-05-21T21:30:00', 57.9800, 11.5600)]
    verdict, _ = p.classify(p.waypoints(rows, tol_m=50))
    assert verdict == 'moving'


def test_a_position_repeated_across_a_time_span_proves_a_stale_fix():
    # 2021-05-18: one position served 8 times over 65 minutes, interleaved with others.
    rows = ([rec(f'2021-05-18T20:1{i}:00', 58.30593, 11.42128) for i in range(3)]
            + [rec('2021-05-18T20:40:00', 58.34531, 11.32868)]
            + [rec(f'2021-05-18T21:1{i}:00', 58.30593, 11.42128) for i in range(3)])
    rp = p.repeats(p.waypoints(rows, tol_m=50))
    assert rp, 'the repeated position should be reported'
    (lat, lon), n, span = rp[0]
    assert abs(lat - 58.30593) < 1e-6
    assert n >= 2 and span > 1800     # spans more than half an hour


def test_wander_ratio_is_near_one_for_a_real_passage():
    # 2021-05-17 Strömstad southward: each leg advances, so path ~= displacement.
    wps = p.waypoints([rec('2021-05-17T15:45:59', 58.69470, 11.17204),
                       rec('2021-05-17T16:57:28', 58.62931, 11.33593),
                       rec('2021-05-17T18:56:06', 58.55451, 11.27337)], tol_m=50)
    assert p.wander(wps) < 1.6


def test_wander_ratio_is_huge_for_a_stationary_scattered_evening():
    # 2021-05-18: 27 sunset photographs from one spot, positions bouncing between
    # three clusters. The boat did not move at all.
    rows = [rec('2021-05-18T20:08:43', 58.31671, 11.40983),
            rec('2021-05-18T20:10:16', 58.30972, 11.37122),
            rec('2021-05-18T20:11:24', 58.30593, 11.42128),
            rec('2021-05-18T20:53:13', 58.25345, 11.44649),
            rec('2021-05-18T21:06:32', 58.35579, 11.23547),
            rec('2021-05-18T21:08:54', 58.31167, 11.41194),
            rec('2021-05-18T21:16:09', 58.30593, 11.42128)]
    assert p.wander(p.waypoints(rows, tol_m=50)) > 10


def test_stationary_day_collapses_to_a_median_not_a_mean():
    # The median must ignore the far outlier; a mean would be dragged toward it.
    rows = [rec('2021-05-18T20:11:24', 58.30593, 11.42128),
            rec('2021-05-18T20:22:09', 58.31400, 11.41592),
            rec('2021-05-18T21:10:30', 58.31181, 11.41212),
            rec('2021-05-18T21:06:32', 58.35579, 11.23547)]   # the outlier
    lat, lon = p.median_position(p.waypoints(rows, tol_m=50))
    assert 58.305 < lat < 58.315
    assert 11.41 < lon < 11.422


def test_scatter_is_not_declared_when_only_one_waypoint_exists():
    wps = p.waypoints([rec('2021-05-21T21:25:46', 57.97654, 11.55662),
                       rec('2021-05-21T21:25:49', 57.97654, 11.55662)], tol_m=50)
    assert p.wander(wps) == 0.0
    assert not p.is_scatter(wps)


def test_is_scatter_flags_the_stationary_evening_but_not_the_passage():
    passage = p.waypoints([rec('2021-05-17T15:45:59', 58.69470, 11.17204),
                           rec('2021-05-17T16:57:28', 58.62931, 11.33593),
                           rec('2021-05-17T18:56:06', 58.55451, 11.27337)], tol_m=50)
    evening = p.waypoints([rec('2021-05-18T20:08:43', 58.31671, 11.40983),
                           rec('2021-05-18T20:10:16', 58.30972, 11.37122),
                           rec('2021-05-18T20:11:24', 58.30593, 11.42128),
                           rec('2021-05-18T21:06:32', 58.35579, 11.23547),
                           rec('2021-05-18T21:16:09', 58.30593, 11.42128)], tol_m=50)
    assert not p.is_scatter(passage)
    assert p.is_scatter(evening)


def test_the_overlay_is_exif_index_s_own_and_honours_drop_and_override(tmp_path):
    """The merge must not be a second implementation of `exif_index.apply_manual`.

    It was, and it silently diverged: this module kept a fill-gaps-only copy written
    before `drop` and `override` existed, so eight corrected 2021-05-17 photographs
    still reported their false Fjällbacka positions while `exif_index.py` reported them
    correctly. Same file, same entries, two different answers.
    """
    import json
    loc = tmp_path / 'manual.json'
    loc.write_text(json.dumps([
        {'path': 'a.jpg', 'lat': 58.58403, 'lon': 11.24750, 'override': True,
         'ashore': False, 'note': 'true position from the seamarks'},
        {'path': 'b.jpg', 'drop': True, 'ashore': False, 'note': 'false, no replacement'},
    ]))
    rows = [rec('2021-05-17T19:06:56', 58.59715, 11.27831, path='a.jpg'),
            rec('2021-05-17T18:56:06', 58.55451, 11.27337, path='b.jpg')]
    merged = {r['path']: r for r in p.apply_overlay(rows, str(loc))}
    assert merged['a.jpg']['lat'] == 58.58403           # overridden
    assert merged['a.jpg']['exif_lat'] == 58.59715      # original kept for audit
    assert merged['b.jpg']['lat'] is None               # dropped


def test_day_rows_are_selected_by_local_date_not_by_timestamp_order():
    rows = [rec('2021-05-16T14:16:35', 57.70359, 11.96965),
            rec('2021-05-17T09:31:01', 58.93891, 11.17589)]
    assert len(p.in_range(rows, '2021-05-17', '2021-05-17')) == 1


# --- feh tagging -----------------------------------------------------------------
#
# The viewer is how the owner finds the two or three photographs on a day that actually
# say where the boat was, and until now that discovery was lost the moment feh closed:
# the filename was on screen and nowhere else. These pin the round trip.


def test_feh_shows_which_file_is_on_screen_and_which_keys_tag_it():
    cmd = p.feh_command(['/a.jpg'], '/tmp/tags.tsv')
    assert '--draw-filename' in cmd     # useless without knowing what one is looking at
    assert '--draw-actions' in cmd      # the key list, so the labels need not be memorised
    assert cmd[-1] == '/a.jpg'


def test_every_tag_gets_its_own_key_with_a_titled_action():
    cmd = p.feh_command(['/a.jpg'], '/tmp/tags.tsv')
    acts = [cmd[i + 1] for i, x in enumerate(cmd) if x.startswith('--action')]
    assert len(acts) == len(p.TAGS)
    for label, a in zip(p.TAGS, acts):
        assert a.startswith(f';[{label}]'), a   # ';' = stay on this image, do not advance


def test_the_action_really_appends_the_filename(tmp_path):
    """Run the generated command through /bin/sh, as feh would.

    This is the test that earns its place. `%s` is a *feh* format specifier - image size
    in bytes - so a printf format written the obvious way is eaten before the shell ever
    sees it, and the tag file silently fills with file sizes instead of separators.
    """
    import subprocess
    tags = tmp_path / 'tags.tsv'
    photo = tmp_path / 'a b.jpg'        # a space, because photograph names have them
    photo.write_bytes(b'')
    cmd = p.feh_command([str(photo)], str(tags), notify=False)
    action = cmd[cmd.index('--action') + 1]
    shell = action.split(']', 1)[1].replace('%F', f"'{photo}'").replace('%%', '%')
    subprocess.run(['/bin/sh', '-c', shell], check=True)
    line = tags.read_text().rstrip('\n')
    stamp, label, path = line.split('\t')
    assert label == 'tag'
    assert path == str(photo)
    assert stamp.startswith('20')


def test_tagging_says_out_loud_that_it_happened():
    """A tag that leaves no visible trace reads as a broken key.

    It did: the `;` flag reloads the same image, so the screen after a successful tag is
    identical to the screen before it, and the first thing the owner did was press the
    key nine times on one photograph believing it dead. The desktop notification is the
    acknowledgement.
    """
    action = p.feh_command(['/a.jpg'], '/tmp/t.tsv')[
        p.feh_command(['/a.jpg'], '/tmp/t.tsv').index('--action') + 1]
    assert 'notify-send' in action
    assert action.index('>>') < action.index('notify-send'), \
        'the tag must be on disk before anything else can fail'
    assert ';' in action[action.index('>>'):action.index('notify-send')], \
        'separated by ; not && - a missing notifier must not swallow the tag'


def test_tags_are_read_back_relative_to_the_photo_root(tmp_path):
    tags = tmp_path / 'tags.tsv'
    tags.write_text(f'2026-08-04T15:00:00+02:00\tashore\t{p.ROOT}/mi/IMG_1.jpg\n'
                    f'2026-08-04T15:01:00+02:00\ttag\t/elsewhere/IMG_2.jpg\n')
    got = p.read_tags(str(tags))
    assert got[0]['path'] == 'mi/IMG_1.jpg'     # matches exif-index.json's keys
    assert got[0]['label'] == 'ashore'
    assert got[1]['path'] == '/elsewhere/IMG_2.jpg'


def test_retagging_a_photograph_corrects_it_rather_than_doubling_it(tmp_path):
    """Pressing another key on the same photograph is how a mistake gets fixed.

    It happens constantly in practice - "I wrongly tagged some aboard-photos with
    on-land" arrived within minutes of the first real use. The file stays an append-only
    log, because when a judgement changed is worth keeping, but the *current* answer is
    the last one, and a photograph must never end up counted as both ashore and afloat.
    """
    tags = tmp_path / 'tags.tsv'
    tags.write_text('2026-08-04T18:10:00\tashore\t/a.jpg\n'
                    '2026-08-04T18:11:00\ttag\t/b.jpg\n'
                    '2026-08-04T18:12:00\tboat\t/a.jpg\n')
    assert len(p.read_tags(str(tags))) == 3, 'the log keeps every keypress'
    assert p.current_tags(p.read_tags(str(tags))) == {'/a.jpg': 'boat', '/b.jpg': 'tag'}


def test_reading_tags_survives_a_missing_or_ragged_file(tmp_path):
    assert p.read_tags(str(tmp_path / 'nope.tsv')) == []
    ragged = tmp_path / 'r.tsv'
    ragged.write_text('\nrubbish\n2026-08-04T15:00:00\ttag\t/a.jpg\n')
    assert [t['path'] for t in p.read_tags(str(ragged))] == ['/a.jpg']


# --- checking a remembered position against the day's fixes -----------------------
#
# The central move of the 2021 method, per TRACKS-2021.md: "Ask the owner, then check
# which cell fix agrees. Twice a remembered position landed within tens of metres of ONE
# of a scattered day's fixes while the rest were miles off." It was being done by hand,
# with the candidate position pasted into a throwaway script, four times in one evening.


def test_a_decimal_position_parses():
    assert p.parse_position('59.887817,10.589383') == (59.887817, 10.589383)
    assert p.parse_position(' 58.18040 , 11.46388 ') == (58.18040, 11.46388)


def test_the_owners_own_format_parses():
    """He types degrees and decimal minutes: 059º53.269' N / 010º35.363' E."""
    lat, lon = p.parse_position("059º53.269' N / 010º35.363' E")
    assert abs(lat - (59 + 53.269 / 60)) < 1e-9
    assert abs(lon - (10 + 35.363 / 60)) < 1e-9


def test_degree_marks_and_separators_vary():
    """Copy-paste turns º into ° or o, and the slash is not always there."""
    want = (59 + 53.269 / 60, 10 + 35.363 / 60)
    for text in ["059°53.269' N 010°35.363' E",
                 "059o53.269' N / 010o35.363' E",
                 "N 059º53.269' E 010º35.363'"]:
        got = p.parse_position(text)
        assert abs(got[0] - want[0]) < 1e-9 and abs(got[1] - want[1]) < 1e-9, text


def test_southern_and_western_hemispheres_are_signed():
    lat, lon = p.parse_position("038º41.049' S / 009º15.314' W")
    assert lat < 0 and lon < 0
    assert abs(lat + (38 + 41.049 / 60)) < 1e-9


def test_nonsense_is_refused_rather_than_guessed():
    for bad in ['', 'Torvøya', '59.887817', '91.0,10.0']:
        with pytest.raises(ValueError):
            p.parse_position(bad)


def test_distances_rank_the_days_waypoints_against_a_candidate():
    """2021-06-08: one cluster 266 m from the Torvøya anchorage, the rest over a km."""
    rows = [rec('2021-06-08T21:48:55', 59.89050, 10.61295),
            rec('2021-06-08T22:42:33', 59.88556, 10.58777),
            rec('2021-06-08T23:40:36', 59.88959, 10.57027)]
    got = p.distances_to(p.waypoints(rows, tol_m=50), (59.887817, 10.589383))
    assert [round(d) for _, d in got] == [267, 1084, 1348], got
    assert got[0][0].first == '2021-06-08T22:42:33', 'nearest first'
