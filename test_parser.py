import gt02a
from point import BoatPosData, Path, ts2dt
import time
import alarm
from unittest.mock import patch

alarm.enable = False
t = time.time()


def check_time(acceptable=3):
    global t
    t2 = time.time()
    assert t2-t < acceptable
    t = t2

## data contains around 15 hours of tracking.
## it should take less than 8 seconds to load
data = gt02a.read_file('test_data.raw')
check_time(8)

@patch('point.alarm')
@patch('point.now')
def test_anchor_alarm(now, alarm):
    def assert_alarm(critical=True):
        assert alarm.call_count == 1
        assert alarm.call_args[0][1] in {True: (2,), False: (0,1)}[critical]
        alarm.call_count = 0
        alarm.call_args = None

    def check_anchorage(series, critical):
        now.return_value = ts2dt(series.all_points[-1].ts)
        series._process_anchorage()
        assert_alarm(critical)
        
    moored_safely = Path([d for d in data if d.ts < '2023-12-30T2030']).split()
    departed_mooring = Path([d for d in data if d.ts < '2023-12-30T2044']).split()
    anchored_safely = Path([d for d in data if d.ts < '2023-12-31T12359']).split()
    drifting = Path([d for d in data if d.ts < '2023-12-31T1052']).split()

    assert drifting.mode == 'sailing'
    assert departed_mooring.mode == 'sailing'
    assert anchored_safely.mode == 'mooring'
    assert moored_safely.mode == 'mooring'

    check_anchorage(moored_safely, False)
    check_anchorage(anchored_safely, False)
    check_anchorage(departed_mooring, True)
    check_anchorage(drifting, True)

    drifting.big_processes()
    anchored_safely.big_processes()
    moored_safely.big_processes()
    departed_mooring.big_processes()
    sailing_summary = drifting.create_summary()
    mooring_summary = anchored_safely.create_summary()
    for series in (moored_safely, departed_mooring, anchored_safely, drifting):
        assert series.redux_points[0].ts.startswith('2023-12-30')

@patch('point.BoatPosData.max_redux_points', 100)
def test_parse_blobs_and_split():
    assert(len(data)>1024)
    my_journey = data.split()
    check_time(30)

    ## The redux point series should not be longer than 100 points.
    assert len(my_journey.redux_points)<=100
    ## The redux should reduce harder the older the data is.  Without redix the midpoint is 2023-12-31T104941.
    mid=len(my_journey.redux_points)//2
    assert my_journey.redux_points[mid].ts > '2024'

    ## moored in cavtat for four hours
    assert my_journey.stop_data[0]['time_moored'].total_seconds()//3600 == 4
    assert my_journey.stop_data[0]['stop_type'] == 'mooring'
    assert len(my_journey.stop_data[0]['mooring_positions']) < 10
    assert len(my_journey.stop_data[0]['sailing_positions']) > 10
    assert my_journey.stop_data[0]['arrival'].startswith('2023-12-30T162')
    assert my_journey.stop_data[0]['departure'].startswith('2023-12-30T204')
    
    ## Anchored up right outside cavtat for 14 hours
    assert my_journey.stop_data[1]['total_sailed_distance']<1000
    assert my_journey.stop_data[1]['total_sailing_time'].total_seconds()<1800
    assert my_journey.stop_data[1]['stop_type'] == 'anchorage'
    assert my_journey.stop_data[1]['time_moored'].total_seconds()//3600 == 14

    ## Moored up again, for almost 8 hours
    assert my_journey.stop_data[2]['total_sailed_distance']<1000
    assert my_journey.stop_data[2]['total_sailing_time'].total_seconds()<1800
    assert my_journey.stop_data[2]['stop_type'] == 'mooring'
    assert (my_journey.stop_data[2]['time_moored'].total_seconds()+600)//3600 == 8

    assert (my_journey.stop_data[-1]['arrival'].startswith('2024-01-01T030') or my_journey.stop_data[-1]['arrival'].startswith('2024-01-01T03'))
    assert (my_journey.mode == 'mooring')

    check_time(0.3)
    b2 = BoatPosData()

    ## data contains 12725 points.  It will unfortunately take significant time to churn one and one point
    for i in range(0, len(data)):
        b2.process_point(data[i])
        if not i%16:
            check_time(0.8)
        if not i%4000 or not i%4003:
            b2.big_processes(force=True)
            check_time(8)

    assert len(b2.all_points) == len(my_journey.all_points)
    assert len(b2.stop_data) == len(my_journey.stop_data)
    
    my_journey.big_processes(force = True)
    b2.big_processes(force=True)
    
    summary1 = b2.create_summary()
    summary2 = my_journey.create_summary()
    summary1.pop('last_big_calc_time')
    summary2.pop('last_big_calc_time')
    
    assert(summary1 == summary2)


    
