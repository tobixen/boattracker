"""Tests for the 2021 raw-feed reader.

Two of these guard mistakes that would be invisible in the output. The archive is rotated
copies of one log, so a reader that does not deduplicate reports several times the fixes that
exist and inflates every per-day count; and the fixes are UTC while the diary is local, so a
reader that splits on the UTC day files an evening arrival under the wrong diary day.
"""

import bz2

import pytest

from boattracker.nfl import tracker_archive
from boattracker.tracker.point import Point, ts2dt


def blob(day, hhmmss, lat_min, lon_min, speed='000.0'):
    """A BR00 fix at 59°lat_min'N 010°lon_min'E - the Oslofjord, where the 2021 feed starts."""
    return (f'(028042516052BR00{day}A59{lat_min}N010{lon_min}E{speed}{hhmmss}000.00'
            '01000000L00000000)')


def test_blobs_are_taken_from_between_the_parentheses():
    raw = (blob('210707', '120000', '53.1866', '35.3712')
           + 'junk from an unauthorized connection'
           + blob('210707', '120015', '53.1870', '35.3754')).encode()
    assert len(tracker_archive.blobs(raw)) == 2
    assert tracker_archive.blobs(raw)[0].startswith(b'028042516052BR00')


def test_an_unterminated_trailing_blob_is_dropped():
    ## Every archive file is a log cut mid-write; the last blob may have no closing paren.
    raw = (blob('210707', '120000', '53.1866', '35.3712')
           + '(028042516052BR00210707A5953.18').encode()
    assert len(tracker_archive.blobs(raw)) == 1


def test_overlapping_files_are_deduplicated(tmp_path):
    ## `foo`, `bar` and the 2021-06-2x files are hand-made copies of stretches the
    ## epoch-named files also hold. Counting them twice would double the day's fixes.
    shared = blob('210707', '120000', '53.1866', '35.3712')
    (tmp_path / 'gpstracker.raw.1.bz2').write_bytes(
        bz2.compress((shared + blob('210707', '120015', '53.1870', '35.3754')).encode()))
    (tmp_path / 'gpstracker.raw.foo').write_bytes(shared.encode())

    points, stats = tracker_archive.read_archive(str(tmp_path))
    assert stats['parsed'] == 3
    assert stats['duplicate'] == 1
    assert len(points) == 2


def test_the_archive_is_sorted_even_when_the_daemon_wrote_out_of_order(tmp_path):
    (tmp_path / 'gpstracker.raw').write_bytes(
        (blob('210707', '120015', '53.1870', '35.3754')
         + blob('210707', '120000', '53.1866', '35.3712')).encode())
    points, _ = tracker_archive.read_archive(str(tmp_path))
    assert [p.ts for p in points] == ['2021-07-07T120000', '2021-07-07T120015']


def test_bad_blobs_are_counted_not_raised(tmp_path):
    (tmp_path / 'gpstracker.raw').write_bytes(
        (blob('210707', '120000', '53.1866', '35.3712')
         + '(028042516052BZ00nonsense)').encode())
    points, stats = tracker_archive.read_archive(str(tmp_path))
    assert len(points) == 1
    assert stats['BZ-blob'] == 1


def test_days_are_local_not_utc():
    ## 22:30 UTC on 07-07 is 00:30 on 07-08 in Sweden in summer, and the diary says 07-08.
    points = [Point(59.0, 10.0, '2021-07-07T223000'), Point(59.0, 10.0, '2021-07-08T060000')]
    assert sorted(tracker_archive.by_day(points, tz_offset=2)) == ['2021-07-08']
    assert sorted(tracker_archive.by_day(points, tz_offset=0)) == ['2021-07-07', '2021-07-08']


def test_thinning_keeps_the_endpoints():
    ## The importer times a fix off the *last* point, so losing the last fix of a day moves
    ## the day's arrival time.
    ## 30 fifteen-second fixes of a boat sitting still, jittering a decimetre at a time.
    points = [Point(59.0 + i / 1000000, 10.0, f'2021-07-07T1200{i:02d}') for i in range(30)]
    kept = tracker_archive.thin(points, min_dist=25, min_secs=60)
    assert len(kept) == 2
    assert kept[0].ts == points[0].ts and kept[-1].ts == points[-1].ts


def test_thinning_keeps_a_fix_that_moved():
    points = [Point(59.0, 10.0, '2021-07-07T120000'),
              Point(59.001, 10.0, '2021-07-07T120015'),   # ~111 m on
              Point(59.002, 10.0, '2021-07-07T120030')]
    assert len(tracker_archive.thin(points, min_dist=25, min_secs=60)) == 3


def test_the_day_table_does_not_count_anchor_jitter_as_travel():
    ## 5 000 fixes a day of a boat sitting still accumulate roughly a mile of GPS noise, so a
    ## day at anchor reads as a day that moved unless the jitter is thinned away first.
    day = [Point(59.0 + (i % 2) / 200000, 10.0, f'2021-07-07T12{i//60:02d}{i%60:02d}')
           for i in range(600)]
    row = next(tracker_archive.summary_rows({'2021-07-07': day}))
    assert row['fixes'] == 600
    assert row['along_nm'] < 0.01


def test_the_day_table_reports_local_clock_times():
    day = [Point(59.0, 10.0, '2021-07-07T220000'), Point(59.0, 10.0, '2021-07-08T060000')]
    row = next(tracker_archive.summary_rows({'2021-07-08': day}, tz_offset=2))
    assert (row['from'], row['to']) == ('00:00', '08:00')


def test_the_speed_the_tracker_reported_separates_a_car_from_a_boat():
    ## The tracker lived aboard but travelled ashore too, and this is the cheapest evidence
    ## there is that a day of movement was not the boat: Solveig does not do 70 km/h.
    ## The single-fix spike is what the percentile is for - GPS speed spikes on its own.
    kmh = [7.0] * 98 + [70.0, 90.0]
    day = [Point(59.0, 10.0, f'2021-07-07T12{i//60:02d}{i%60:02d}', speed=s / 3.6)
           for i, s in enumerate(kmh)]
    row = next(tracker_archive.summary_rows({'2021-07-07': day}))
    assert row['kn95'] == pytest.approx(7.0 / 1.852, rel=0.01)
    assert row['kn_max'] == pytest.approx(90.0 / 1.852, rel=0.01)


def test_a_day_the_tracker_never_reported_a_speed_still_gets_a_row():
    day = [Point(59.0, 10.0, '2021-07-07T120000'), Point(59.0, 10.0, '2021-07-07T130000')]
    assert next(tracker_archive.summary_rows({'2021-07-07': day}))['kn95'] == 0.0


def test_holes_ignore_the_routine_reconnect_but_catch_a_lost_passage():
    ## The tracker drops out for ~9 minutes every two hours all summer - that is the GSM
    ## session restarting, not a hole in the record. A hole worth knowing about is one the
    ## boat moved across, because the track over it is a straight line and not evidence.
    points = [Point(59.0, 10.0, '2021-07-02T080000'),
              Point(59.0, 10.0, '2021-07-02T080920'),          # 9.3 min, stationary
              Point(59.0, 10.0, '2021-07-02T081000'),
              Point(59.0, 10.4, '2021-07-02T140000')]          # 5.8 h, 12 nm on
    assert tracker_archive.holes(points, min_minutes=30) == tracker_archive.holes(points)
    (start, end, minutes, nm), = tracker_archive.holes(points, min_minutes=30)
    assert start.ts == '2021-07-02T081000' and end.ts == '2021-07-02T140000'
    assert minutes == pytest.approx(350, abs=1)
    assert nm == pytest.approx(12.3, abs=0.3)


def test_a_photograph_is_matched_to_the_fix_nearest_it_in_time():
    ## EXIF times are local and carry no timezone; the tracker is UTC. Comparing them
    ## without the two-hour shift matches a photograph against the boat's position two hours
    ## earlier, which on a passage is ten miles away and looks like a contradiction.
    track = [Point(59.0, 10.0, '2021-07-07T100000'),
             Point(59.1, 10.0, '2021-07-07T110000')]
    photo = {'time': '2021-07-07T13:00:00', 'lat': 59.1, 'lon': 10.0}
    (rec, fix, metres), = tracker_archive.match_photos(track, [photo], tz_offset=2)
    assert fix.ts == '2021-07-07T110000'
    assert metres < 1


def test_a_photograph_far_from_any_fix_in_time_is_not_matched():
    track = [Point(59.0, 10.0, '2021-07-07T100000')]
    photo = {'time': '2021-07-07T20:00:00', 'lat': 59.0, 'lon': 10.0}
    assert tracker_archive.match_photos(track, [photo], max_minutes=30) == []


def test_photographs_without_a_position_or_a_time_are_skipped():
    track = [Point(59.0, 10.0, '2021-07-07T100000')]
    photos = [{'time': '2021-07-07T12:00:00', 'lat': None, 'lon': None},
              {'time': None, 'lat': 59.0, 'lon': 10.0}]
    assert tracker_archive.match_photos(track, photos) == []


def ts(minute_of_day):
    return f'2021-07-07T{minute_of_day//60:02d}{minute_of_day % 60:02d}00'


def sail(start, minutes, lat0=59.0, step=0.002):
    """A boat moving steadily north at ~7 kn, one fix a minute from `start` (minute of day)."""
    return [Point(lat0 + i * step, 10.0, ts(start + i), speed=3.5) for i in range(minutes)]


def still(start, minutes, lat=59.0):
    """A boat sitting still, one fix a minute."""
    return [Point(lat, 10.0, ts(start + i), speed=0.0) for i in range(minutes)]


def test_a_leg_is_cut_every_second_clock_hour_under_way():
    ## One GPX is one fix timestamped at its last point, so a fix every second hour means a
    ## cut every second hour - and on the even hour itself, not at some offset from the start.
    legs = tracker_archive.segments(sail(10 * 60 + 30, 8 * 60), hours=2)
    assert [leg[-1].ts for leg in legs[:3]] == ['2021-07-07T120000', '2021-07-07T140000',
                                               '2021-07-07T160000']


def test_a_short_hop_between_hours_is_not_cut():
    ## The daemon's rule: a clock hour only ends a leg once the leg is worth reporting -
    ## half an hour and a mile of it. Otherwise a boat crossing a harbour at 11:59 files two.
    assert len(tracker_archive.segments(sail(11 * 60 + 50, 20), hours=2)) == 1


def test_a_leg_ends_where_the_boat_stops():
    ## The arrival is the fix that dates the stop, so the leg must end *there* and not run on
    ## through the hours at the berth. The berth itself is not a leg - it is not movement.
    points = sail(10 * 60, 60) + still(11 * 60, 120, lat=59.12) + sail(13 * 60, 60, lat0=59.12)
    legs = tracker_archive.segments(points, hours=2)
    assert legs[0][-1].ts == '2021-07-07T110000'          # arrival ends the leg
    assert legs[1][0].ts == '2021-07-07T130000'           # the next leg starts on departure
    assert all(leg[0].distance_to(leg[-1]) > 100 for leg in legs)


def test_hours_at_anchor_are_not_an_hourly_fix():
    points = sail(10 * 60, 30) + still(10 * 60 + 30, 480, lat=59.06)
    assert len(tracker_archive.segments(points, hours=2)) == 1


def test_a_drifting_anchor_watch_is_not_a_leg():
    ## A boat swinging 170 m round its anchor over eight hours defeats the stop detector -
    ## no half-hour window stays inside the radius of where it started - and would be filed
    ## as a leg that sailed a tenth of a mile at nought knots.
    ## 33 m every ten minutes for eight hours: too fast to hold still inside the radius,
    ## far too slow to be under way.
    drift = [Point(59.078 + i * 0.0003, 10.0, ts(10 * 60 + 40 + i * 10), speed=0.0)
             for i in range(48)]
    for leg in tracker_archive.segments(sail(10 * 60, 40) + drift, hours=2):
        along, _ = tracker_archive.travelled(leg)
        hours = (ts2dt(leg[-1].ts) - ts2dt(leg[0].ts)).total_seconds() / 3600
        assert along / 1852 / hours >= 0.5, f'{leg[0].ts}..{leg[-1].ts} is not a passage'


def test_a_hole_in_the_feed_always_ends_a_leg():
    ## A leg spanning an unrecorded stretch would draw a straight line over it and present
    ## interpolation as track.
    legs = tracker_archive.segments(sail(10 * 60, 20) + sail(17 * 60, 20, lat0=59.5), hours=2)
    assert len(legs) == 2
    assert legs[0][-1].ts == '2021-07-07T101900'


def test_an_arrival_on_the_far_side_of_a_hole_does_not_bridge_it():
    ## The 2021-07-02 shape, and the worst thing this tool could do: the boat lies still all
    ## morning, the feed dies for six hours, and it comes back 10 nm away and lies still
    ## again. Arrival and break coincide, and if the arrival is appended the leg draws a line
    ## across water the tracker never saw - interpolation filed as evidence.
    points = still(0, 120) + still(8 * 60, 120, lat=59.2)
    for leg in tracker_archive.segments(points, hours=2):
        assert leg[0].distance_to(leg[-1]) < 1000, 'a leg bridged the hole'


def test_a_leg_of_no_duration_is_not_a_leg():
    ## Two fixes 70 m apart sharing a timestamp are a GPS artefact, not a passage, and they
    ## slip past a speed floor that can only divide by a positive number of hours.
    points = [Point(59.0, 10.0, '2021-07-07T120000'), Point(59.001, 10.0, '2021-07-07T120000')]
    assert tracker_archive.segments(points, hours=2) == []


def test_travelled_measures_along_the_track_and_the_line():
    points = [Point(59.0, 10.0, '2021-07-07T120000'),
              Point(59.1, 10.0, '2021-07-07T130000'),
              Point(59.0, 10.0, '2021-07-07T140000')]
    along, direct = tracker_archive.travelled(points)
    assert along == pytest.approx(2 * 11119, rel=0.01)
    assert direct == pytest.approx(0, abs=1)


def test_reading_a_date_range_skips_the_fixes_outside_it(tmp_path):
    ## The archive also holds 2023-2025 now, ~300 MB; parsing it all to look at three weeks
    ## of 2021 took over five minutes a run. The window is in local days, so a fix late on
    ## the UTC day before the range can still belong to its first local day and must be kept.
    (tmp_path / 'gpstracker.raw').write_bytes(
        (blob('210706', '120000', '53.1866', '35.3712')       # local 07-06, outside
         + blob('210706', '223000', '53.1866', '35.3712')     # local 07-07 00:30, inside
         + blob('210707', '120000', '53.1870', '35.3754')
         + blob('240707', '120000', '53.1870', '35.3754')     # 2024, outside
         + '(028042516052BZ00nonsense)').encode())
    points, stats = tracker_archive.read_archive(str(tmp_path), lo='2021-07-07',
                                                 hi='2021-07-07', tz_offset=2)
    assert [p.ts for p in points] == ['2021-07-06T223000', '2021-07-07T120000']
    assert stats['outside range'] == 1, 'counts the blobs skipped unparsed, not edge fixes'
    assert stats['BZ-blob'] == 1, 'a blob of no known date is still parsed and counted'


def test_gaps_are_listed_for_the_requested_days_only(tmp_path, monkeypatch, capsys):
    raw = ''.join(blob(day, hhmmss, '53.1866', lon)
                  for day, hhmmss, lon in [
                      ('210706', '080000', '35.3712'), ('210706', '140000', '45.3712'),
                      ('210707', '080000', '35.3712'), ('210707', '140000', '45.3712'),
                      ('210708', '080000', '35.3712'), ('210708', '140000', '45.3712')])
    (tmp_path / 'gpstracker.raw').write_bytes(raw.encode())
    monkeypatch.setattr('sys.argv', ['tracker_archive', '--archive', str(tmp_path),
                                     '--from', '2021-07-07', '--to', '2021-07-07', '--gaps'])
    tracker_archive.main()
    out = capsys.readouterr().out
    assert '2021-07-07T080000   2021-07-07T140000' in out
    assert '2021-07-06T' not in out.split('UTC\n', 1)[1]
    assert '2021-07-08T' not in out.split('UTC\n', 1)[1]
    assert '\n1 breaks over 30 minutes' in out


def test_a_login_blob_is_dated_like_a_plain_fix():
    login = b'028042516052BP05355228042516052210822A5751.2556N01139.7108E005.1185957'
    assert tracker_archive.blob_date(login) == '2021-08-22'
    assert tracker_archive.blob_date(b'028042516052BR00210822A5751.2638N') == '2021-08-22'


def test_a_zero_dated_blob_is_left_to_the_parser():
    ## The parser calls a 000000 date "fake news"; skipping it as outside the window would
    ## hide that from the error count.
    assert tracker_archive.blob_date(b'028042516052BR00000000A5751.2638N') is None


def test_the_upper_edge_of_the_window_follows_the_offset(tmp_path):
    ## West of UTC the local day ends after the UTC day does: 03:00 UTC on 07-08 is still
    ## 07-07 at -5 h, and must be kept by a --to of 07-07 alone.
    (tmp_path / 'gpstracker.raw').write_bytes(
        (blob('210707', '120000', '53.1866', '35.3712')
         + blob('210708', '030000', '53.1866', '35.3712')     # local 07-07 22:00, inside
         + blob('210708', '120000', '53.1870', '35.3754')     # local 07-08, outside
         + blob('210710', '120000', '53.1870', '35.3754')).encode())   # skipped unparsed
    points, stats = tracker_archive.read_archive(str(tmp_path), hi='2021-07-07', tz_offset=-5)
    assert [p.ts for p in points] == ['2021-07-07T120000', '2021-07-08T030000']
    assert stats['outside range'] == 1


def test_without_clock_hours_a_passage_is_one_leg():
    ## The owner's rule since 2026-08-14: one fix per leg, stop to stop. Eight hours under
    ## way between two stops is one leg, whatever the clock says.
    points = still(9 * 60, 60) + sail(10 * 60, 8 * 60, lat0=59.0) + still(18 * 60, 60, lat=59.96)
    legs = tracker_archive.segments(points, hours=None)
    assert len(legs) == 1
    assert legs[0][-1].ts == '2021-07-07T180000'


def night_passage(tmp_path):
    """22:30 .. 02:30 local (20:30 .. 00:30 UTC) under way, an hour still at each end."""
    fixes = []
    for minute in range(0, 6 * 60):              # 19:30 .. 01:29 UTC, one fix a minute
        utc = 19 * 60 + 30 + minute
        day, hhmm = ('210707', utc) if utc < 24 * 60 else ('210708', utc - 24 * 60)
        under_way = min(max(minute - 60, 0), 240)
        lat_min = f'{10 + under_way * 0.12:07.4f}'
        fixes.append(blob(day, f'{hhmm // 60:02d}{hhmm % 60:02d}00', lat_min, '35.3712'))
    (tmp_path / 'gpstracker.raw').write_bytes(''.join(fixes).encode())


def test_a_leg_runs_over_midnight_in_leg_mode(tmp_path, monkeypatch):
    ## A night passage, 22:30 .. 02:30 local, between an hour at each end: one leg and one
    ## file, not one per diary day.
    night_passage(tmp_path)
    out = tmp_path / 'out'
    monkeypatch.setattr('sys.argv', ['tracker_archive', '--archive', str(tmp_path),
                                     '--from', '2021-07-07', '--to', '2021-07-08',
                                     '--legs', '--write', '--out', str(out)])
    tracker_archive.main()
    assert sorted(p.name for p in out.iterdir()) == ['tracker2021-2021-07-07-2230-0230.gpx']


def test_a_leg_is_split_at_a_requested_instant():
    ## The owner's exception to stop-to-stop, 2026-11-26: a 43 h passage split at UTC
    ## midnight so the day in the middle gets a fix of its own. The two halves share the
    ## last fix before the cut, so the drawn line stays continuous.
    legs = tracker_archive.segments(sail(10 * 60, 8 * 60), hours=None)
    split = tracker_archive.split_at(legs, [ts2dt('2021-07-07T140000')])
    assert len(split) == 2
    assert split[0][-1].ts == '2021-07-07T135900'
    assert split[1][0].ts == '2021-07-07T135900'
    assert split[1][-1].ts == legs[0][-1].ts
    assert len(split[0]) + len(split[1]) == len(legs[0]) + 1


def test_a_split_instant_outside_every_leg_changes_nothing():
    legs = tracker_archive.segments(sail(10 * 60, 60), hours=None)
    assert tracker_archive.split_at(legs, [ts2dt('2021-07-07T200000')]) == legs


def test_several_instants_cut_one_leg_into_several():
    legs = tracker_archive.segments(sail(10 * 60, 8 * 60), hours=None)
    split = tracker_archive.split_at(legs, [ts2dt('2021-07-07T160000'), ts2dt('2021-07-07T120000')])
    assert [(leg[0].ts, leg[-1].ts) for leg in split] == [
        ('2021-07-07T100000', '2021-07-07T115900'),
        ('2021-07-07T115900', '2021-07-07T155900'),
        ('2021-07-07T155900', legs[0][-1].ts)]


def test_an_instant_after_the_first_fix_only_leaves_the_leg_whole():
    ## One fix before the cut would be a first half of a single point: not a leg.
    legs = tracker_archive.segments(sail(10 * 60, 60), hours=None)
    assert tracker_archive.split_at(legs, [ts2dt('2021-07-07T100030')]) == legs


def test_an_instant_on_a_fix_ends_the_first_half_just_before_it():
    legs = tracker_archive.segments(sail(10 * 60, 60), hours=None)
    split = tracker_archive.split_at(legs, [ts2dt('2021-07-07T103000')])
    assert split[0][-1].ts == '2021-07-07T102900'


@pytest.mark.parametrize('instant', ['2021-07-07T22:00', '2021-07-07T22:00Z',
                                     '2021-07-08T00:00+02:00'])
def test_split_at_from_the_command_line_takes_utc_with_or_without_an_offset(
        tmp_path, monkeypatch, instant):
    night_passage(tmp_path)
    out = tmp_path / 'out'
    monkeypatch.setattr('sys.argv', ['tracker_archive', '--archive', str(tmp_path),
                                     '--from', '2021-07-07', '--to', '2021-07-08',
                                     '--legs', '--split-at', instant,
                                     '--write', '--out', str(out)])
    tracker_archive.main()
    names = sorted(p.name for p in out.iterdir())
    assert len(names) == 2
    assert names[0].startswith('tracker2021-2021-07-07-2230-')
    assert names[1].endswith('-0230.gpx')


def test_split_at_without_legs_is_refused(tmp_path, monkeypatch):
    night_passage(tmp_path)
    monkeypatch.setattr('sys.argv', ['tracker_archive', '--archive', str(tmp_path),
                                     '--split-at', '2021-07-07T22:00', '--write',
                                     '--out', str(tmp_path / 'out')])
    with pytest.raises(SystemExit):
        tracker_archive.main()

