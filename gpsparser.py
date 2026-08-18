#!/usr/bin/python


__version__ = '0.0.3'

from geopy.distance import distance as geo_distance
import sys
import asyncio
import itertools
import json
import logging
import requests
import datetime
import math
import subprocess
import socket

sys.path.append('.')

import parser
#from secret import push_token

def alarm(msg, level=2):
    lvltxt={0: 'OK', 1: 'WARNING', 2: 'CRITICAL'}
    subprocess.run(["/usr/bin/sudo", "/usr/local/sbin/send-mod-gearman", "/etc/mod-gearman/send-mod-gearman.conf"],
                   input=f"{socket.gethostname()}\tSolveig may be drifting\t{level}\t{lvltxt[level]}: $msg".encode('utf-8'))

class Point:
    def __init__(self, lat, long, ts="", heading=None, speed=None, colour="r") -> None:
        self.lat = lat
        self.long = long
        self.colour = colour
        self.ts = ts
        self.heading = heading
        self.speed = speed

    def distance_to(self, other):
        return geo_distance(self.tuple, other.tuple).meters

    def time_delta(self, other):
        tsobjs = [datetime.datetime.strptime(ts, "%Y-%m-%dT%H%M%S") for ts in [self.ts, other.ts]]
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

    @property
    def tuple(self): return self.lat, self.long

    @property
    def string(self): return f"{self.long:.5f},{self.lat:.5f},{self.colour},{self.ts[11:13]}"

class BoatPosData():
    def __init__(self):
        self.points = []
        self.heading = None
        self.speed = 0
        self.swing_radius = 0
        self.summary = {}
        
    def big_calc(self):
        self.anchoring_time = "1970-01-01"
        self.expected_swing_radius=50
        try:
            with open('/var/www/html/solveig.oslo.no/anchoring_time', 'r') as f:
                self.anchoring_time = f.readline().strip()
            with open('/var/www/html/solveig.oslo.no/anchoring_expected_swing_radius', 'r') as f:
                self.expected_swing_radius = float(f.readline().strip())
        except:
            pass

        self.outliers = redux([x for x in self.points if x.ts>self.anchoring_time], 0.1, datetime.timedelta(seconds=14), 60)
        max_distance = 0
        outliers2 = []
        for twopoints in itertools.combinations(self.outliers, 2):
            distance = twopoints[0].distance_to(twopoints[1])
            if distance > max_distance:
                outliers2 = twopoints
                max_distance = distance
        self.outliers2 = outliers2
        self.max_distance = max_distance
        midpoint = Point(0,0,colour='g', ts='1970-01-01Txxxxxx')

        if self.outliers2:
            midpoint.lat = sum([p.lat for p in self.outliers2])
            midpoint.lat /= len(self.outliers2)
            midpoint.long = sum([p.long for p in self.outliers2])
            midpoint.long /= len(self.outliers2)

        else:
            midpoint = self.points[-1]
        self.midpoint = midpoint
        self.points[-1].colour = 'b'
        
        self.small_calc()

    def small_calc(self):
        max_lat = max([point.lat for point in self.points])
        min_lat = min([point.lat for point in self.points])
        max_long = max([point.long for point in self.points])
        min_long = min([point.long for point in self.points])

        self.summary['distance'] = self.points[-1].distance_to(self.midpoint)
        self.summary['ts'] = self.points[-1].ts
        self.summary['lastpos'] = (self.points[-1].lat, self.points[-1].long)
        self.summary['estimated_anchorpos'] = (self.midpoint.lat, self.midpoint.long)
        self.summary['box'] = [[min_lat, min_long], [max_lat,max_long]]
        self.summary['anchor_bearing'] = self.midpoint.bearing(self.points[-1])
        self.summary['heading'] = self.heading
        self.summary['speed'] = self.speed
        self.summary['expected_swing_radius'] = self.expected_swing_radius

        if self.outliers2:
            self.swing_radius = self.midpoint.distance_to(self.outliers2[0])
            if (self.expected_swing_radius < self.swing_radius):
                alarm(f"Observed swing radius is {self.swing_radius:.1f}, which is higher than expected {self.expected_swing_radius:.1f}", 2)
            elif (self.expected_swing_radius < self.swing_radius*0.9):
                alarm(f"Observed swing radius is {self.swing_radius:.1f}, which is near the expected {self.expected_swing_radius:.1f}", 1)
            elif (self.summary['distance'] > self.swing_radius*0.99):
                alarm(f"Distance to anchor is probably {self.summary['distance']}, which is near the maximum observed swing radios {self.swing_radius:.1f}", 1)
            else:
                alarm(f"Distance to anchor is probably {self.summary['distance']}, maximum observed swing radius is {self.swing_radius:.1f}", 0)

        self.summary['swing_radius'] = self.swing_radius
        
def redux(points, min_dist, min_time, max_points):
    overshoot_add = 0.08
    pot = 1.2
    time_discount = 3
    points_redux = []
    lastpoint = None
    min_time_cnt = 0
    min_dist_cnt = 0
    for point in points:
        if lastpoint and -lastpoint.time_delta(point)<min_time:
            min_time_cnt += 1
            continue
        
        if lastpoint and lastpoint.distance_to(point)<min_dist:
            min_dist_cnt += 1
            continue

        lastpoint=point
        points_redux.append(point)

    print(f"DEBUG: killed due to distance: {min_dist_cnt:3d} - killed due to time: {min_time_cnt:3d}")
    print("DEBUG: original points: %i" % len(points))
    print("DEBUG: redux points: %i" % len(points_redux))
    if len(points_redux)>max_points:
        overshoot_factor = len(points_redux)/max_points
        print("DEBUG: overshoot factor: %.2f.  min distance: %.2f.  min time: %s. points: %i" % (overshoot_factor, min_dist, min_time, len(points_redux)))
        return redux(points, min_dist*(overshoot_factor+overshoot_add)**(pot*((min_time_cnt+0.5)/(0.5+min_time_cnt+min_dist_cnt*time_discount))), min_time*(overshoot_factor+overshoot_add)**(pot*((min_dist_cnt*time_discount+0.5)/(0.5+min_time_cnt+min_dist_cnt*time_discount))), max_points)
    else:
        print("DEBUG: distance steps in meters: %.2f" % min_dist)
        print("DEBUG: time steps: %s" % str(min_time))
        return points_redux


def find_distance(pos1, pos2):
    return geo_distance(pos1.tuple,pos2.tuple).meters

def read_file():
    with open('gpstracker.raw', 'rb') as foofile:
        content=foofile.read()
    data = parser.parse_blobs(content)
    assert(data is not None)
    for x in data:
        assert(x is not None)
    points = [Point(lat=x[0], long=x[1], ts=x[2], speed=x[3], heading=x[4]) for x in data]
    return points

async def receive_blobs(reader, writer, mypos):
    ## TODO: not in use yet
    while True:
        try:
            blob = await asyncio.wait_for(reader.readuntil(b')'), timeout=60)
        except:
            logging.critical("exception found", exc_info=True)
            writer.close()
            break
        with open('gpstracker.raw', 'ab') as rawfile:
            rawfile.write(blob)
            rawfile.write(b'\n')
        point = parser.parse_blob(blob)
        if point:
            points.append(Point(lat=x[0], long=x[1], ts=x[2]))

def main():
    mypos = BoatPosData()
    mypos.points = read_file()
    mypos.big_calc()

    mypos.outliers2[0].colour = 'g'
    mypos.outliers2[1].colour = 'g'

    #import pdb; pdb.set_trace()

    #finnpoints.append(midpoint)

    mypos.points[-1].colour = 'b'

    #finnpoints.append(points[-1])

    print(f"DEBUG: max distance: {mypos.max_distance:.1f}")

    #finnpoints = [x for x in finnpoints if x['color'] != 'r']

    #finnurl="https://kart.finn.no/?lng=10.48015&lat=59.83833&zoom=18&mapType=norortho&markers="
    #finnurl+='%7C'.join([x.string for x in finnpoints])
    #summary['finnurl'] = finnurl

    #print("\n".join(["{lat},{long}".format(**point) for point in points]))

    with open('anchoring-summary.json', 'w') as f:
        json.dump(mypos.summary, f, indent=4)

    redux_points = redux(mypos.points, 0.02, datetime.timedelta(seconds=4), 65534)
    data = [[p.lat, p.long, p.ts] for p in redux_points]
    #redux_data = [[p.lat, p.long, p.ts] for p in somepoints]

    with open('anchoring-geojson.json', 'w') as f:
        json.dump(parser.geojson(data), f)

    #with open('anchoring-geojson-redux.json', 'w') as f:
    #    json.dump(parser.geojson(redux_data), f)
        
    with open('anchoring-jtt.json', 'w') as f:
        json.dump(parser.jtt(data), f)

    #with open('anchoring-jtt-redux.json', 'w') as f:
    #    json.dump(parser.jtt(redux_data), f)
        
if __name__ == '__main__':
    try:
        main()
    except:
        #alarm("exception in gps parsing script")
        logging.error("exception found", exc_info=True)
