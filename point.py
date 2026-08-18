from geopy.distance import distance as geo_distance
import datetime
import time
import math
import re
import itertools
from dataclasses import dataclass, field, astuple
from alarm import alarm
import json

now = datetime.datetime.now

## Timestamps are typically recorded as strings in this format
fmt = "%Y-%m-%dT%H%M%S"
def ts2dt(ts):
    return datetime.datetime.strptime(ts, fmt)
def dt2ts(dt):
    return dt.strftime(fmt)

@dataclass
class Point:
    """
    at some timestamp (string as for now) the boat was located at some coordinates.
    gps tracker also delivers heading, speed and altitude, though I'm not using those fields as for now
    """
    lat: float
    long: float
    ts: str = field(default=None)
    speed: float = field(default=None)
    heading: float = field(default=None)
    ## more fields may be added like this:
    #tmptest1: str = field(default=None)
    #tmptest2: str = field(default=None)

    def gpx_trkpt(self):
        gpxts = lambda ts: f"{ts[0:13]}:{ts[13:15]}:{ts[15:17]}Z"
        return f"""<trkpt lat="{self.lat}" lon="{self.long}"><time>{gpxts(self.ts)}</time></trkpt>"""

    def distance_to(self, other):
        return geo_distance(self.ctuple, other.ctuple).meters

    def time_delta(self, other):
        tsobjs = [ts2dt(ts) for ts in [self.ts, other.ts]]
        return tsobjs[0]-tsobjs[1]

    def bearing(self, other):
        """
        Calculates the bearing between two points, copied from https://gist.github.com/jeromer/2005586 
        """
        lat1 = math.radians(self.lat)
        lat2 = math.radians(other.lat)

        diffLong = math.radians(other.long - self.long)

        x = math.sin(diffLong) * math.cos(lat2)
        y = math.cos(lat1) * math.sin(lat2) - (math.sin(lat1)
                * math.cos(lat2) * math.cos(diffLong))

        initial_bearing = math.atan2(x, y)

        # Now we have the initial bearing but math.atan2 return values
        # from -180° to + 180° which is not what we want for a compass bearing
        # The solution is to normalize the initial bearing as shown below
        initial_bearing = math.degrees(initial_bearing)
        compass_bearing = (initial_bearing + 360) % 360

        return compass_bearing

    ## ctuple - coordinate tuple with two coordinates.  ftuple - full tuple.
    @property
    def ctuple(self): return self.lat, self.long

    @property
    def ftuple(self): return astuple(self)

    @property
    def string(self): return f"{self.ts}: {self.long:.5f},{self.lat:.5f}"

    def __str__(self): return self.string

class Path(list):
    """
    A path is basically just a list of points, but may contain extra meta information or calculated information, like ...
    sailing, mooring or anchoring?
    average velocity?  distance sailed?  vmg?
    """
    def export_gpx(self):
        header = """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="BoatTracker"><trk><name>SY Solveig - track from Chinese GPS-tracker on board</name><trkseg>
        """
        track = [header]
        for i in range(0, len(self)):
            track.append(self[i].gpx_trkpt())
        track.append("""</trkseg></trk></gpx>""")
        return "\n".join(track)
            
    def redux(self, *largs, **kwargs):
        """
        Reduce the amount of points, by deleting points that are close to each other in time or space, middle points on a straight line, and (when moored) "freak points"-noise due to inaccurate GPS.
        """
        points_redux = ReduxPath(self, *largs, **kwargs)

        for i in range(0, len(self)):
            points_redux.process_point(self[i], len(self)-i)
        return points_redux

    def analyze_sailing(self):
        if not len(self):
            return {'total_sailed_distance': 0, 'total_sailing_time': datetime.timedelta(microseconds=1)}
        sailing_time = self[-1].time_delta(self[0])
        many_points = self.redux(8, datetime.timedelta(seconds=10), 2048, useless_time_multiplier=32, drop_freak=False, useless_deviation_multiplier=1.01)
        significant_points = self.redux(9, datetime.timedelta(seconds=10), 1024, useless_time_multiplier=128, drop_freak=False, useless_deviation_multiplier=1.02)
        tot_sailed_dist = 0
        redux_tot_sailed_dist = 0
        for i in range(1, len(significant_points)):
            redux_tot_sailed_dist += significant_points[i].distance_to(significant_points[i-1])
        for i in range(1, len(many_points)):
            tot_sailed_dist += many_points[i].distance_to(many_points[i-1])
        return {'total_sailed_distance': tot_sailed_dist, 'redux_sailed_distance': redux_tot_sailed_dist, 'total_sailing_time': self[-1].time_delta(self[0]), 'sailing_positions': self}

    def split(self, max_distance_1=30, max_distance_2=120, max_speed_knots=0.5):
        stops = BoatPosData()
        stops.all_points = self
        stops.redux_points.parent = self

        max_speed = max_speed_knots*0.514444 ## m/s

        for point in self:
            stops._process_point_stop(point, max_distance_1, max_distance_2, max_speed)
            if not stops._has_stopped and len(stops._prev_near_positions)>500:
                import pdb; pdb.set_trace()
            stops.redux_points.process_point(point)
        if not stops._has_stopped and len(stops._prev_near_positions)>500:
            import pdb; pdb.set_trace()
        stops._post_process_stops()

        return stops

    def box(self):
        corners = []
        for m in (min, max):
            corner = []
            for i in (0, 1):
                corner.append(m([x.ctuple[i] for x in self]))
            corners.append(corner)
        return corners

    def geojson(self):
        """Takes a simple points list and returns a data set that will
        conform to the GEOJson RFC7946 format if saved through the json
        module.  (There also exists a geojson module, should eventually
        consider to use that)
        """
        mypoints = [[point.long, point.lat] for point in self]
        data={
            'type': 'Feature',
            'properties': {},
            'geometry': {
                'type': 'LineString',
                'coordinates': mypoints
            }
        }
        return data

    def jtt(self, title="Anchor drift", desc="Tracking of the vessel S/Y Solveig LJ6994 while staying by anchor"):
        """
        ref https://dret.typepad.com/dretblog/2015/11/gps-data-on-the-web.html
        """
        data = {
            "JTT": [
                { "track": {
                    "title": title,
                    "desc": desc,
                    "segments": [
                        {"data-fields": ["latitude", "longitude", "timestamp"]},
                        [[x.lat, x.long, x.ts] for x in self]
                    ]
                }}
            ]
        }
        return data

class MooringPath(Path):
    ## A mooring path has a redux mooring position set
    def __init__(self):
        ## Mostly due to GPS inaccuracies, a mooring position may vary with around 6 meters.
        ## Let's eliminate all points nearer than X meters and see what we end up with.
        self._mooring_positions = ReduxPath(self, 6, datetime.timedelta(seconds=4), 512, useless_time_multiplier=0, drop_freak=512)
        
    def append(self, obj):
        if len(self):
            assert len(self._mooring_positions)
        self._mooring_positions.process_point(obj)
        Path.append(self, obj)
        if len(self):
            assert len(self._mooring_positions)

    def extend(self, objs):
        for obj in objs:
            self.append(obj)

    def analyze_stop(self):
        if not len(self) or not len(self._mooring_positions):
            ## There is nothing to analyze here
            return
        
        ## There are (roughly) four kind of stops - anchorings, moorings, drop off/on, and false positives.
        ## This method should ideally manage to identify what kind of stop it is.
        ## Regular moorings should be trivial to identify - boat should be stuck at the same position for most of the time.  Before and after, there is some noise as we're struggling with getting moored and leaving.

        stop_time = self[-1].time_delta(self[0])

        assert self._mooring_positions[0].ts <= self._mooring_positions[-1].ts

        max_time = datetime.timedelta(seconds=0)
        last_point = None
        for point in self._mooring_positions + [self[-1]]:
            if not last_point:
                last_point = point
                continue
            pos_time = point.time_delta(last_point)
            if pos_time > max_time:
                max_time_point = last_point
                max_time = pos_time
                ## mooring departure time.  This will be wrong for anchorages.
                mdt = point.ts
            last_point = point

        ## Code to identify a "proper mooring".
        ## We define a "proper mooring" to be something lasting for more than 15 minutes
        if stop_time.total_seconds() > 900:
            ## We define a "proper mooring" to be that we've spent at least 80% of the stopping time at the same spot:
            if max_time/stop_time > 0.8:
                return {
                    "stop_type": "mooring",
                    "position": max_time_point,
                    "arrival": max_time_point.ts,
                    "departure": mdt,
                    "time_moored": max_time,
                    "mooring_positions": self._mooring_positions,
                }

        ## If the stop lasts for more than an hour, and
        ## there is more than 10 points in the mooring_positions, and
        ## no points dominate the time taken, then
        ## assume anchorage, otherwise unknown
        stop_type = 'unknown'
        if stop_time.total_seconds()>3600 and len(self._mooring_positions)>10 and max_time/stop_time < 0.4:
            stop_type = 'anchorage'

        ## Anything else is "unknown" as for now, and actual position set to the point where we've spent most time:
        return {
            "stop_type": stop_type,
            "position": max_time_point,
            "arrival": self[0].ts,
            "departure": self[-1].ts,
            "time_moored": stop_time,
            "mooring_positions": self._mooring_positions
        }

@dataclass
class ReduxPath(Path):
    """
    A ReduxPath is a path where points that are close to each other in time or space, are on the middle of a straight line, or (when moored) are considered to be "freak noise" due to inaccurate GPS, may have been deleted.

    A ReduxPath always have a parent containing all the points

    A ReduxPath has various tweakable settings.

    A ReduxPath can receive one and one point, and decide weather to discard it, keep it, or discard the previous point.
    """
    ## TODO: document all those tweakables.  Give them better names.
    ## TODO: take real-world data and visualize the results to tweak
    ## the tweakables and the algorithms better.
    parent: Path
    min_dist: float = field(default=4)
    min_time: datetime.timedelta = field(default = datetime.timedelta(seconds=7))
    max_points: int = field(default=0)
    useless_time_multiplier: float = field(default=4)
    useless_deviation_multiplier: float = field(default=1.01)
    drop_freak: float = field(default=0)
    long_dist: float = field(default=256)
    timegap_threshold: datetime.timedelta = field(default=None)
    gaps: list = field(default_factory=lambda: [])
    overshoot_add: float = field(default=0.08)
    pot: float = field(default=1.2)
    time_discount: float = field(default=3)
    recursive_drop_old_data: float = field(default=0)

    _lastpoint: Point = field(default=None)
    _last2point: Point = field(default=None)
    _useless_cnt: int = field(default=0)
    _freak_cnt: int = field(default=0)
    _tot_cnt: int = field(default=0)
    _min_time_cnt: int = field(default=0)
    _min_dist_cnt: int = field(default=0)
    _lastlegdistance: int = field(default=0)
    _last2legdistance: int = field(default=0)

    def process_point(self, point, cnt_remaining=0):
        ## TODO:
        ## points are now killed based on either distance in meters, distance in time, "lineliness" aka "uselessness" or "freakyness" (noise).  For the first three we should probably use some bayesian logic rather than boolean logic to decide which points to discard.
        self._tot_cnt += 1

        if self._lastpoint:
            assert(self._lastpoint == self[-1])
            if point.ts < self._lastpoint.ts:
                timejump = self._lastpoint.time_delta(point)
                if timejump.total_seconds()>600:
                    import pdb; pdb.set_trace()
                print(f"ERROR: Ignoring FREAK TIME TRAVELING POINT - last point: {self._lastpoint.ts} - delta: {self._lastpoint.time_delta(point)}")
                return
            timedelta = point.time_delta(self._lastpoint)

            if timedelta>=self.min_time:
                self._last2legdistance = self._lastlegdistance
                self._lastlegdistance = self._lastpoint.distance_to(point)

            if self.timegap_threshold and timedelta>self.timegap_threshold and self._lastlegdistance>self.long_dist:
                print(f"gap found lasting {timedelta}, from {self._lastpoint.ts} - {point.ts} - {self._lastlegdistance}m")
                self.gaps.append([self._lastpoint,point])

            if timedelta<self.min_time:
                self._min_time_cnt += 1
                return

            if self._lastlegdistance<self.min_dist:
                self._min_dist_cnt += 1
                return

        if self._last2point:
            self._last2totdistance = self._last2point.distance_to(point)

        if (self.drop_freak and ## freak mooring points detection
            self._last2point and ## (gps anomalies)
            self._tot_cnt > (self._freak_cnt+0.1)*self.drop_freak and ## "freak" as in low frequency
            self._last2totdistance < self.min_dist ## we're standing still
            ):
            assert self.pop() == self._lastpoint
            self._lastpoint = self[-1]
            self._freak_cnt += 1

            assert(self._lastpoint == self[-1])
            if self._tot_cnt > self._freak_cnt*self.drop_freak:
                print(f"DEBUG: killed as freak points: {self._freak_cnt}")
                self._tot_cnt = 0
                self._freak_cnt = 0

            return

        if (self._last2point and
            (point.time_delta(self._last2point)<self.min_time*self.useless_time_multiplier) and
            (self._lastlegdistance < (self._last2totdistance-self._last2legdistance) * self.useless_deviation_multiplier ** (self.long_dist/(self.long_dist+self._last2totdistance)))):
            ## Three points almost on a line, last point (middle point) relays very little extra information, so it may be discarded
            assert self.pop() == self._lastpoint
            self._lastpoint = self[-1]
            self._useless_cnt += 1
        else:
            self._last2point = self._lastpoint

        self._lastpoint = point
        self.append(point)
        assert(self._lastpoint == self[-1])

        if len(self)>self.max_points:
            ## Too many points - let's try to run the redux algorithm once more with slightly more aggressive parameters.

            ## "Overshoot factor" is used to determine how much to adjust the limits
            if not cnt_remaining:
                cnt_remaining = 1 + len(self)/100.0
            overshoot_factor = (len(self)+cnt_remaining)/self.max_points
            print("DEBUG: overshoot factor: %.2f.  min distance: %.2f.  min time: %s, udm: %4.2f. points: %i" % (overshoot_factor, self.min_dist, self.min_time, self.useless_deviation_multiplier, len(self)))

            ## Let's reset the state (but not the configuration) of the object
            if self.recursive_drop_old_data:
                ## todo ... lots of copying data.  But it's cheap nowadays, even for large lists.  Back in the 1980s this was a no-no ...
                oldlist = self.copy()
            else:
                oldlist = self.parent
            del self[0:]
            self._lastpoint = None
            self._last2point = None
            self._useless_cnt = 0
            self._freak_cnt = 0
            self._tot_cnt = 0
            self._min_time_cnt = 0
            self._min_dist_cnt = 0
            self._lastlegdistance = 0
            self._last2legdistance = 0

            ## Let's adjust the configuration to restrict the number of allowable points
            self.min_dist *= (overshoot_factor+self.overshoot_add)**(self.pot*((self._min_time_cnt+0.5)/(0.5+self._min_time_cnt+self._min_dist_cnt*self.time_discount)))
            self.min_time *= (overshoot_factor+self.overshoot_add)**(self.pot*((self._min_dist_cnt*self.time_discount+0.5)/(0.5+self._min_time_cnt+self._min_dist_cnt*self.time_discount)))
            self.useless_time_multiplier += 2 ## TODO: hard-coded constant
            self.useless_deviation_multiplier += 0.02 ## TODO: hard-coded constant

            ## Initialized as 1 rather than 0 to preserve the first point in the list
            dropped = 1
            processed = 0
            for i in range(0, len(oldlist)):
                processed += 1
                if oldlist[i].ts>point.ts:
                    break
                if self.recursive_drop_old_data>dropped/processed:
                    dropped += 1
                    break
                self.process_point(oldlist[i], len(self.parent)-i)

class BoatPosData:
    """
    BoatPosData contains historic and current information on the boat position(s), stops, etc.

    The most important attributes is the stop_data, containing metainformation on all stops, the all_points containing all points, redux_points with a slightly reduced amount of points, and the anchor alarm functionality also populates some information into the object.
    """
    max_redux_points=44444
    def __init__(self):
        self.mode = None
        self._has_stopped = False
        self._last_near_positions = Path()
        self._prev_near_positions = MooringPath()
        self._sailing_points = Path()
        self._lastnear = None
        self.stop_data = []
        self.all_points = Path()
        self.last_big_calc_time = 0
        self._pending_gpxexport = Path()
        self.last_gpxexport_time = 0
        self.redux_points = ReduxPath(self.all_points, 0.2, datetime.timedelta(seconds=2.32), self.max_redux_points, useless_time_multiplier=40, timegap_threshold=datetime.timedelta(hours=2), recursive_drop_old_data=0.5)

    def _analyze(self, departured, export_gpx=True):
        """
        * analyze with departured=True should be run as soon as we're leaving a stop.  Metadata on the stop will then be archived - with sailing data leading up until the stop and full stop data.
        * analyze with departured=False should be run when we're staying at some stop.  Metadata about the stop will be calculated.
        """
        if self.stop_data and self.stop_data[-1]['departure'] != 'NA':
            assert self.stop_data[-1]['departure'] <= (self._prev_near_positions+self._last_near_positions)[-1].ts
        if len(self._prev_near_positions) and not len(self._last_near_positions):
            some_points = self._prev_near_positions
        else:
            some_points = MooringPath()
            for point in self._prev_near_positions + self._last_near_positions:
                some_points.append(point)
            
        new_stop_data = some_points.analyze_stop()
        if not departured: ## intermediate calculation.  We're still moored up.  Departure should be NA.
            new_stop_data['departure'] = 'NA'
        if not self.mode == 'mooring':
            ## The current stop hasn't been recorded yet
            self.stop_data.append(new_stop_data)
            ## Analyze and add sailing data - this is the data leading up until the mooring
            self.stop_data[-1].update(self._sailing_points.analyze_sailing())
            ## TODO: sailing_points could be reset now?
            self.mode = 'mooring'
        else:
            ## Current stop has already been recorded, and should be updated rather than added
            self.stop_data[-1].update(new_stop_data)
        if self._last_near_positions and departured:
            import pdb; pdb.set_trace()
        for attr in self.stop_data[-1]:
            if not attr.endswith('positions'):
                print(f"DEBUG: {attr:20s}: {self.stop_data[-1][attr]}")
        if export_gpx:
            if self._sailing_points:
                sailing_gpx = self._sailing_points.export_gpx()
                with open(f"sailing{self._sailing_points[0].ts}.gpx", "w") as f:
                    f.write(sailing_gpx)
            if some_points:
                moored_gpx = some_points.export_gpx()
                with open(f"moored{some_points[0].ts}.gpx", "w") as f:
                    f.write(moored_gpx)

    def big_processes(self, force=False, min_interval=10):
        """
        Some processing that takes time and probably shouldn't be run for every point we're receiving.

        This algorithm will do heavy lifting with a minimum interval of 60 seconds.

        TODO: still lots of room for optimizations should it take too much time.
        """
        if not force:
            if (now() - ts2dt(self.all_points[-1].ts)).total_seconds()>60:
                return False
            if time.time()-self.last_big_calc_time < min_interval:
                return False

        self.last_big_calc_time = time.time()

        print(f"TIMING DEBUG: big calc started")
        self._post_process_stops()
        print(f"TIMING DEBUG {time.time()-self.last_big_calc_time:.2f}s - after post_process_stops")
        if self.stop_data:
            self._process_anchorage()
        print(f"TIMING DEBUG {time.time()-self.last_big_calc_time:.2f}s - after process_anchorage")
        self.write_files()
        print(f"TIMING DEBUG: big calc took {time.time()-self.last_big_calc_time:.2f}s")
        self.last_big_calc_time = time.time()
        
    def process_point(self, point):
        """
        process a new point.
        """
        if self.all_points:
            assert point.ts >= self.all_points[-1].ts
        self.all_points.append(point)
        self._process_point_stop(point)
        self.redux_points.process_point(point)
        ## TODO
        #self._process_point_redux()
        self.big_processes()

    def _process_anchorage(self, max_drift=1852, anchorage_set_time=1200, alarm_period=3700):
        """
        Try to figure out where the anchor is sitting (may require one to take the boat for a full circle around the anchor once anchored up), yield alarms when the boat is leaving the anchorage (which may happen due to anchor dragging or problems with the rope).  Also, make alarms when the boat is leaving a mooring (which may happen because lines are snapping or due to sabotage)
        """
        ## TODO: optimize this into _process_point_anchorage (but redux needs optimization first), we don't need to do all the calculations on every run
        
        ## Data may be fed manually, by altering files on the server
        try:
            with open('/var/www/html/solveig.oslo.no/anchoring_time', 'r') as f:
                self.anchor_time = f.readline().strip()
        except:
            if self.stop_data:
                self.anchor_time = self.stop_data[-1]['arrival']
            else:
                self.anchor_time = dt2ts(now())

        try:
            with open('/var/www/html/solveig.oslo.no/anchoring_expected_swing_radius', 'r') as f:
                self.expected_swing_radius = float(f.readline().strip())
                anchorage_set_time=0
        except:
            if self.stop_data[-1]['stop_type'] == 'mooring':
                self.expected_swing_radius = 9
            else:
                self.expected_swing_radius = None ## calculate later based on anchorage_set_time

        if not self.expected_swing_radius and self.mode == 'sailing' and self.stop_data[-1]['departure'] != 'NA' and (now() - ts2dt(self.stop_data[-1]['departure'])).total_seconds() > alarm_period:
            alarm(f"Anchoring alarm is disabled, we're probably sailing", 0)
            return

        important_points = [x for x in self.all_points if x.ts>self.anchor_time]
        if not important_points:
            alarm(f"Anchoring alarm is disabled, missing data", 3)
            return
        if anchorage_set_time:
            setting_time = dt2ts(ts2dt(self.anchor_time) + datetime.timedelta(seconds=anchorage_set_time))
            anchor_setting_points = [x for x in important_points if x.ts<setting_time]
        else:
            anchor_setting_points = important_points

        ## algorithm for finding the anchor point.
        ## TODO: this assumes we've been swinging at least 180 degrees around, figure out a more advanced approach.
        ## TODO: make a ReduxPath-object and insert points on every iteration rather than recalculating it every so often
        self.anchor_outliers = Path(anchor_setting_points).redux(0.1, datetime.timedelta(seconds=12), 60, useless_deviation_multiplier=1.08)
        max_distance = 0
        outliers2 = []
        for twopoints in itertools.combinations(self.anchor_outliers, 2):
            distance = twopoints[0].distance_to(twopoints[1])
            if distance > max_distance:
                outliers2 = twopoints
                max_distance = distance
        self.anchor_outliers2 = outliers2
        self.max_distance = max_distance
        midpoint = Point(0,0)
        if self.anchor_outliers2:
            midpoint.lat = sum([p.lat for p in self.anchor_outliers2])
            midpoint.lat /= len(self.anchor_outliers2)
            midpoint.long = sum([p.long for p in self.anchor_outliers2])
            midpoint.long /= len(self.anchor_outliers2)
        else:
            midpoint = important_points[-1]
        self.estimated_anchor_point = midpoint.ctuple
        self.anchor_bearing = midpoint.bearing(self.all_points[-1])
        self.anchor_distance = midpoint.distance_to(self.all_points[-1])
        if self.mode == 'sailing' and self.anchor_distance>max_drift:
            alarm(f"Anchoring alarm is disabled, we've probably sailed away from the anchorage", 0)
        elif self.anchor_outliers2:
            self.anchor_swing_radius = midpoint.distance_to(self.anchor_outliers2[0])
            if not self.expected_swing_radius:
                self.expected_swing_radius = self.anchor_swing_radius*1.2
            if (self.anchor_distance > self.expected_swing_radius):
                alarm(f"Distance from anchor is {self.anchor_distance:.1f}, which is higher than expected {self.expected_swing_radius:.1f}", 2)
            elif (float(self.expected_swing_radius) < self.anchor_swing_radius*0.95 and self.expected_swing_radius!=self.anchor_swing_radius):
                alarm(f"Observed swing radius is {self.anchor_swing_radius:.1f}, which is near the expected {self.expected_swing_radius:.1f}", 1)
            elif (self.anchor_distance > self.anchor_swing_radius*0.98):
                alarm(f"Distance to anchor is probably {self.anchor_distance:.1f}, which is near the maximum observed swing radios {self.anchor_swing_radius:.1f}", 1)
            else:
                alarm(f"Distance to anchor is probably {self.anchor_distance:.1f}, maximum observed swing radius is {self.anchor_swing_radius:.1f}", 0)
        else:
            alarm(f"Anchoring alarm is disabled, we're probably not anchored", 0)

    def flush_gpxexport(self):
        if not len(self._pending_gpxexport):
            return
        fn = f'export-{self._pending_gpxexport[-1].ts}.gpx'
        print(f"DEBUG: flush gpx: {fn}")
        with open(fn, 'w') as f:
            f.write(self._pending_gpxexport.export_gpx())
        self._pending_gpxexport = Path()
            
    def _process_point_stop(self, point, max_distance_1=30, max_distance_2=120, max_speed=0.257222, export_gpx=True):
        """
        Take a point, look at it, determinate weather we're sailing, moored, or has just left a mooring.
        
        If we've just left a mooring:
        * call self._analyze to analyze the stop and gather metadata
        * set self.mode = 'sailing' and self._has_stopped = False
        * export GPX data
        
        If we've just stopped:
        * set self._has_stopped = True
        * export GPX data
        
        If more than X seconds and Y meter since last export of GPX - or a gap in the data:
        * export GPX
        """
        if export_gpx:
            ## Trying to improve readability a bit by introducing lots of temporary logic variables ...
            if self._pending_gpxexport:
                ## a gap in the data lasting for at least two hours, and significant movement during those two hours
                gap_in_data = point.time_delta(self._pending_gpxexport[-1])>datetime.timedelta(minutes=120) and point.distance_to(self._pending_gpxexport[-1])>1852

                ## Significant amount of pending points, or significant distance covered
                significant_pending = len(self.redux_points)>32 and self.redux_points[-32].ts>self._pending_gpxexport[0].ts and self._pending_gpxexport[0].distance_to(point)>1852

                ## at least half an hour worth of significant logging, and we've just passed a clock hour (make the NFL fixtures neat with one fixture for each clock hour)
                clock_hour_logic = significant_pending and point.time_delta(self._pending_gpxexport[0])>datetime.timedelta(minutes=30) and re.search('T..0[01234]', point.ts)
                
                ## more than two hours worth of significant logging (in case we lost the clock hour logic above)
                lost_clock_hour_logic = significant_pending and point.time_delta(self._pending_gpxexport[0])>datetime.timedelta(minutes=120)

                clock_export = clock_hour_logic or lost_clock_hour_logic
            else:
                gap_in_data = False
                clock_export = False
                

            ## On a data gap, it's important that the GPX export does not cover the gap - so the point we're looking at should be in the next import
            if gap_in_data:
                print("DEBUG: gap in data, flushing gpxexport")
                self.flush_gpxexport()

            self._pending_gpxexport.append(point)
            
            ## The clock logic is to create nice-looking timestamps.  It should be 13:00:00 rather than 12:59:59.  Hence flushing has to be done after adding the point. As for the lost_clock_hour_logic, it does not matter much, but best to yield the freshest data possible.
            if clock_export:
                print("DEBUG: clock export, flushing gpxexport")
                self.flush_gpxexport()
                
        if len(self._prev_near_positions):
            assert len(self._prev_near_positions._mooring_positions)
        
        ## TODO: hard coded constant 1800s below
        ## Initialize _lastnear if possible
        if not self._lastnear:
            self._lastnear = point
            assert len(self._prev_near_positions) == 0
            return
        distance_lastnear = self._lastnear.distance_to(point)

        if len(self._prev_near_positions):
            assert len(self._prev_near_positions._mooring_positions)
        
        ## count some statistics
        if self._last_near_positions:
            duration = self._last_near_positions[-1].time_delta(self._last_near_positions[0])
            ## More than three minutes travelling less than 30
            ## meter distance - so avg less than 0.31 knots for
            ## more then three minutes - we count that as a stop.
            if duration.total_seconds() > 180:
                if not self._has_stopped:
                    print("DEBUG: new stop (180s), flush gpxexport")
                    self.flush_gpxexport()
                self._has_stopped = True
            elif len(self._last_near_positions)>180:
                import pdb; pdb.set_trace()

        ## Collect all near points into _last_near_position list
        if distance_lastnear < max_distance_1:
            self._last_near_positions.append(point)
            if len(self._last_near_positions)>180 and not self._has_stopped:
                import pdb; pdb.set_trace()

        else:
            ## Could be:
            ## Case 1: It could be that we're leaving a stop
            ## Case 2: It could be that we're moving around an anchor.
            ## Case 3: It could be that we're slowly drifting somewhere
            ## Case 4: It could be that we're moving somewhere

            ## Identified as such:
            ## Case 1a: We have started moving at max_speed or more and we have a stop series 
            ## Case 1b: We have below max_speed, have moved 120 meters away from the first point in the series, but the series has lasted for more than 30 minutes (drifting with avg speed < 0.13 knots => false positive)
            ## Case 2: We have moved less than 120 meters away from our starting point and are moving below max_speed
            ## Case 3: We have moved more than 120 meters away from the starting point
            ## Case 4: We're moving at max_speed or more and we do not have a stop series

            ## Should be handled like this:

            ## In any case, move self._last_near_positions onto self._prev_near_positions.  Set _lastnear to point

            ## Case 1: analyze the stop, analyze the sailing, nullify near data, nullify sailing data
            ## Case 2: continue collecting near data
            ## Case 3 and 4: move data to the sailing and nullify self._prev_near_positions

            ## Possibly pitfalls that probably should be fixed:
            ## 1) Swinging faster than 0.5 knots while anchored (not observed problems with that yet)
            ## 2) Slowing down to 0.4 knots for a couple of minutes, then speeding up to 0.5 knots (we possibly have some false positives already due to that)
            ## 3) leaving from a place in less than 0.5 knots
            
            ## In any case ... (ref comments above)
            self._prev_near_positions.extend(self._last_near_positions)
            self._last_near_positions = Path()
            if len(self._prev_near_positions)>480 and not self._has_stopped:
                import pdb; pdb.set_trace()

            ## count some statistics 2
            speed = distance_lastnear/(point.time_delta(self._lastnear).total_seconds()+0.1)
            if self._prev_near_positions:
                stop_duration = self._prev_near_positions[-1].time_delta(self._prev_near_positions[0])
                stop_distance = self._prev_near_positions[-1].distance_to(self._prev_near_positions[0])
                stop_dur_secs = stop_duration.total_seconds()
            else:
                stop_dur_secs = 0
                stop_distance = 0

            if stop_dur_secs > 1800:
                if not self._has_stopped:
                    print("DEBUG: new stop (1800s), flush gpxexport")
                    self.flush_gpxexport()
                self._has_stopped = True

            ## In any case ... (continued)
            self._lastnear = point

            ## case 1a or 1b - leaving a dock or anchorage
            ## TODO: remove hard coded constants!
            if ((speed > max_speed and self._has_stopped) or ## 1a
                (stop_distance > max_distance_2 and self._has_stopped)):
                self._has_stopped = False
                self._analyze(departured=True)
                self.mode = 'sailing'
                self._sailing_points = Path([point])
                self._prev_near_positions = MooringPath()
                print("DEBUG: left stop, flush gpxexport")
                self.flush_gpxexport()

            ## case 3 and case 4
            elif (stop_distance > max_distance_2 or
                  speed > max_speed):
                self._sailing_points.extend(self._prev_near_positions)
                self._sailing_points.append(point)
                self._prev_near_positions = MooringPath()
                ## TODO ... this should not be needed?
                self.mode = 'sailing'
                
                if len(self._prev_near_positions)>500:
                    import pdb; pdb.set_trace()

            else: ## case 2
                if len(self._prev_near_positions)>500 and not self._has_stopped:
                    import pdb; pdb.set_trace()
                self._prev_near_positions.append(point)

        if len(self._prev_near_positions):
            assert len(self._prev_near_positions._mooring_positions)
            
        if len(self._prev_near_positions)>500 and not self._has_stopped:
            import pdb; pdb.set_trace()

    def _post_process_stops(self):
        ## TODO: Why? Why? Why?  And what happens if I delete this?
        #if self._prev_near_positions and self._last_near_positions:
        #    assert(self._prev_near_positions[-1].ts <= self._last_near_positions[0].ts)
        #self._prev_near_positions.extend(self._last_near_positions)
        #self._last_near_positions = Path()

        if self._has_stopped:
            ## Real-time information indicates that we're stuck at some mooring.  A full analyze is done when we leave the mooring, but we should do an intermedient analyze to get this right.
            ## We should reanalyze the situation
            self._analyze(departured=False)

    def create_summary(self):
        self.last_pos = self.all_points[-1].ctuple
        self.last_ts = self.all_points[-1].ts
        self.big_box = self.all_points.box()
        if self.stop_data:
            self.last_mooring_box = self.stop_data[-1]['mooring_positions'].box()
            self.last_sailing_box = self.stop_data[-1]['sailing_positions'].box()

        summary = {}
        for x in self.__dict__.keys():
            if not x.startswith('_') and not x in ('stop_data', 'all_points', 'redux_points', 'anchor_outliers', 'anchor_outliers2'):
                summary[x] = self.__dict__[x]
        summary['gps_heading'] = self.all_points[-1].heading
        summary['gps_speed'] = self.all_points[-1].speed
        if self.stop_data:
            lo = {}
            li = self.stop_data[-1]

            summary['last_stop'] = lo
            for x in li:
                if not x.endswith('positions'):
                    if hasattr(li[x], 'total_seconds'):
                        lo[x] = str(li[x])
                    elif hasattr(li[x], 'strftime'):
                        lo[x] = dt2ts(li[x])
                    elif hasattr(self.stop_data[-1][x], 'ftuple'):
                        summary['last_stop'][x] = self.stop_data[-1][x].ftuple
                    else:
                        summary['last_stop'][x] = self.stop_data[-1][x]
        return summary

    def write_summary(self):
        with open('summary.json', 'w') as f:
            json.dump(self.create_summary(), f, indent=4)

    def write_legacy_summary(self):
        legacy_summary = {
            'distance': self.__dict__.get('anchor_distance', 0),
            'ts': self.last_ts,
            'lastpos': self.last_pos,
            'estimated_anchorpos': self.__dict__.get('estimated_anchor_point', self.last_pos),
            'box': self.big_box,
            'anchor_bearing': self.__dict__.get('anchor_bearing', 0),
            'expected_swing_radius': self.__dict__.get('expected_swing_radius', 0)
        }
        with open('anchoring-summary.json', 'w') as f:
            json.dump(legacy_summary, f, indent=4)

    def write_stop_log(self):
        stops_serialized = []
        sailing_serialized = []
        gaps_serialized = []
        prev_stop = None
        for gap in self.redux_points.gaps:
            jump_distance = gap[0].distance_to(gap[1])
            jump_distance_nm = jump_distance/1852
            jump_time = gap[1].time_delta(gap[0])
            jump_vmg_knots = jump_distance_nm/jump_time.total_seconds()*3600
            gaps_serialized.append({
                'jump_from': gap[0].ftuple,
                'jump_to': gap[1].ftuple,
                'jump_distance': jump_distance,
                'jump_distance_nm': jump_distance_nm,
                'jump_vmg_knots': jump_vmg_knots,
                'jump_time': str(jump_time),
                'jump_time_seconds': jump_time.total_seconds()
            })
        for stop in self.stop_data:
            if prev_stop:
                if prev_stop['departure'] != 'NA':
                    assert prev_stop['departure'] <= stop['arrival']
                startpos = prev_stop['mooring_positions'][-1]
                stoppos = stop['mooring_positions'][0]
                airdist = stoppos.distance_to(startpos)
                timetaken = stoppos.time_delta(startpos)
                fuzz_factor = stop['redux_sailed_distance']/(stop['total_sailed_distance']+0.00001)-1
                sailing_serialized.append({
                    'start': startpos.ts,
                    'stop': stoppos.ts,
                    'time_sailed': str(timetaken),
                    'air_distance_meters': airdist,
                    'air_distance_nm': airdist/1852,
                    'sailed_distance_meters': stop['total_sailed_distance'],
                    'sailed_distance_nm': stop['total_sailed_distance']/1852,
                    'avg_speed_knots':stop['total_sailed_distance']/timetaken.total_seconds()/1852*3600,
                    'avg_vmg_knots': airdist/timetaken.total_seconds()/1852*3600,
                    'fuzz_factor': f"{fuzz_factor*100:.2f}%"
                })
            stops_serialized.append({
                'stop_type': stop['stop_type'],
                'position': f"{stop['position'].lat},{stop['position'].long}",
                'position_gmaps_url': f"https://www.google.com/maps/place/{stop['position'].lat},{stop['position'].long}/@{stop['position'].lat},{stop['position'].long},12z?entry=ttu",
                'position_oss_url': f"https://www.openstreetmap.org/?mlat={stop['position'].lat}&mlon={stop['position'].long}#map=12/{stop['position'].lat}/{stop['position'].long}",
                'arrival': stop['arrival'],
                'departure': stop['departure'],
                'time_moored': str(stop['time_moored']),
                'time_moored_seconds': stop['time_moored'].total_seconds()
            })
            prev_stop = stop
        with open('stops.json', 'w') as f:
            json.dump({'stops': stops_serialized, 'sailing': sailing_serialized, 'gaps': gaps_serialized}, f, indent=4)
        sailing_serialized.append({
            'start': 'NA',
            'stop': 'NA',
            'time_sailed': 'NA',
            'air_distance_meters': 0,
            'air_distance_nm': 0,
            'avg_vmg_knots': 0,
            'sailed_distance_meters': 0,
            'sailed_distance_nm': 0
        })
        num_stops = len(stops_serialized)
        with open('stops.log', 'w') as f:
            for i in range(0, num_stops):
                stop = stops_serialized[i]
                sailing = sailing_serialized[i]
                ## Arriving and departuring from a place only if staying there for some time
                if stop['time_moored_seconds'] > 1800:
                    f.write("* {arrival} UTC: arrived at {stop_type} {position} (XXX)\n* {departure} UTC: departed from {stop_type} after {time_moored}\n".format(**stop))
                else:
                    f.write("* {arrival} UTC: stop or standstill ({stop_type}) at {position} (XXX) for {time_moored}\n".format(**stop))
                if i < num_stops-1:
                    ## Sailing time
                    if sailing['air_distance_meters']<1852:
                        distance = f"{int(sailing['air_distance_meters'])}m"
                        sailed_distance = f"{int(sailing['sailed_distance_meters'])}m"
                    else:
                        distance = f"{sailing['air_distance_nm']:.1f}nm"
                        sailed_distance = f"{sailing['sailed_distance_nm']:.1f}nm"
                    f.write("* {start} UTC: moved for {time_sailed}, line distance {distance}, sailed distance {sailed_distance} ({fuzz_factor}), avg speed {avg_speed_knots:.1f} kts, vmg {avg_vmg_knots:.1f} kts\n".format(**sailing, distance=distance, sailed_distance=sailed_distance))

    def write_jtt(self):
        with open('jtt.json', 'w') as f:
            json.dump(self.redux_points.jtt(), f)

    def write_geojson(self):
        with open('geojson.json', 'w') as f:
            json.dump(self.redux_points.geojson(), f)

    def write_files(self):
        self.write_summary()
        self.write_legacy_summary()
        self.write_stop_log()
        self.write_jtt()
        self.write_geojson()

## TODO: renaming stops -> ?, prepend internal attributes with _, ...
