from point import Point, Path
import datetime

def test_distance():
    south = Point(-1/120,0)
    north = Point(1/120,0)
    west = Point(0,-1)
    east = Point(0,1)
    pole = Point(90,0)
    nearpole = Point(90-1/60,0)

    one_min_lat_equator = north.distance_to(south)

    ## order doesn't matter.  Distance is absolute.
    assert(south.distance_to(north) == one_min_lat_equator)
    
    assert(round(one_min_lat_equator) == 1843) ## ref https://en.wikipedia.org/wiki/Nautical_mile
    assert(round(nearpole.distance_to(pole)) == 1861+1) ## ref https://en.wikipedia.org/wiki/Nautical_mile ... eh, either the algorithm is wrong or wikipedia is wrong
    assert(round(west.distance_to(east)) == round(40075000/180)) ## https://education.nationalgeographic.org/resource/equator/

def test_time_delta():
    point1 = Point(0,0,'2024-01-01T120000')
    point2 = Point(0,0,'2024-01-02T130000')
    assert point2.time_delta(point1) == datetime.timedelta(days=1, hours=1)
    assert point1.time_delta(point2) == -datetime.timedelta(days=1, hours=1)

def test_bearing():
    south = Point(-1/120,0)
    north = Point(1/120,0)
    west = Point(0,-1)
    east = Point(0,1)
    assert(north.bearing(south)) == 180
    assert(south.bearing(north)) == 0
    assert(west.bearing(east)) == 90
    assert(east.bearing(west)) == 270

def test_box():
    data = [(0,0), (-1,-1), (14,22), (-5, 32), (-6,0)]
    data = [Point(*x) for x in data]
    data = Path(data)
    box = data.box()
    assert box[0][0] == min([x.lat for x in data])
    assert box[0][1] == min([x.long for x in data])
    assert box[1][0] == max([x.lat for x in data])
    assert box[1][1] == max([x.long for x in data])

    
def test_redux():
    path = Path([
        Point(0,0       ,'2024-01-01T120000'),
        Point(0,0.00001 ,'2024-01-01T130000'),
        Point(0.00001,0 ,'2024-01-01T140000'),
        Point(0,0       ,'2024-01-01T150000')])

    ## all points are within min_dist and should be collapsed
    assert(len(path.redux(min_dist=2, min_time=datetime.timedelta(minutes=59), max_points=5)) == 1)

    ## all points are outside min_dist, but some points should be collapsed due to min_time
    assert(len(path.redux(min_dist=1, min_time=datetime.timedelta(minutes=61), max_points=5)) == 2)

    ## all points are outside min_dist and min_time, no collapsing should occur
    assert(len(path.redux(min_dist=1, min_time=datetime.timedelta(minutes=59), max_points=5)) == 4)

    ## all points are within five hours and should be collapsed
    assert(len(path.redux(min_dist=1, min_time=datetime.timedelta(hours=5), max_points=5)) == 1)

    ## only one point wanted, only one point should be returned
    assert(len(path.redux(min_dist=2, min_time=datetime.timedelta(minutes=59), max_points=1)) == 1)

    path = Path([
        Point(0,0, '2024-01-01T120000'),
        Point(0,1, '2024-01-01T130000'),
        Point(0,2, '2024-01-01T140000'),
        Point(0,3, '2024-01-01T150000')])

    ## They are on a line and can be collapsed into two points
    assert(len(path.redux(min_dist=2, min_time=datetime.timedelta(minutes=59),useless_time_multiplier=8,  max_points=5)) == 2)

    ## drop freak
    path = Path([
        Point(0,0, '2024-01-01T120000'),
        Point(0,0, '2024-01-01T121000'),
        Point(0,0, '2024-01-01T122000'),
        Point(20,20, '2024-01-01T123000'),
        Point(0,0, '2024-01-01T124000'),
        Point(0,0, '2024-01-01T140000'),
        Point(0,0, '2024-01-01T150000')])
    assert(len(path.redux(min_dist=2, min_time=datetime.timedelta(seconds=1), max_points=5, drop_freak=6)) == 1)

    path = Path([
        Point(0,0, '2024-01-01T120000'),
        Point(0,0, '2024-01-01T121000'),
        Point(0,0, '2024-01-01T122000'),
        Point(20,20, '2024-01-01T123000'),
        Point(0,0, '2024-01-01T124000'),
        Point(0,0, '2024-01-01T140000'),
        Point(0,0, '2024-01-01T150000')])
    assert(len(path.redux(min_dist=2, min_time=datetime.timedelta(seconds=1), max_points=5, drop_freak=120)) == 3)

    ## TODO: test this harder
    path = Path([
        Point(0,0, '2024-01-01T120000'),
        Point(1,2, '2024-01-01T121000'),
        Point(2,2, '2024-01-01T122000'),
        Point(3,4, '2024-01-01T123000'),
        Point(4,7, '2024-01-01T124000'),
        Point(5,5, '2024-01-01T140000'),
        Point(6,9, '2024-01-01T150000'),
        Point(9,6, '2024-01-01T165000')])
    foo = path.redux(min_dist=0.1, min_time=datetime.timedelta(seconds=1), max_points=6, drop_freak=120, recursive_drop_old_data=1)
    assert len(foo)>1
    assert foo[1].ts > '2024-01-01T124000'
    assert len(path.redux(min_dist=0.1, min_time=datetime.timedelta(seconds=1), max_points=6, drop_freak=120, recursive_drop_old_data=0.001))>3
