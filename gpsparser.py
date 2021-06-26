#!/usr/bin/python

import sys

__version__ = '0.0.2'

from geopy.distance import distance as geo_distance
import itertools
import json
import logging
import requests
import datetime
import math

sys.path.append('.')

import parser
from secret import push_token

def alarm(msg):
    requests.post("https://api.pushover.net/1/messages.json", json={"token":push_token,"user":"u8qz7uu2fc64gonrjsbbkts67omba2","message":msg})
    logging.critical("alarm - pushing to cellphone: %s\n" % msg)


class Point:
    def __init__(self, lat, long, ts="", colour="r") -> None:
        self.lat = lat
        self.long = long
        self.colour = colour
        self.ts = ts

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

def redux(points, min_dist, min_time, max_points):
    max_distance=90
    points_redux = []
    lastpoint = None
    for point in points:
        if lastpoint and -lastpoint.time_delta(point)<min_time:
            continue
        
        if lastpoint and lastpoint.distance_to(point)<min_dist:
            continue

        lastpoint=point
        points_redux.append(point)

    if len(points_redux)>max_points:
        overshoot_factor = len(points_redux)/max_points
        print("DEBUG: overshoot factor: %.2f.  min distance: %.2f.  min time: %s. points: %i" % (overshoot_factor, min_dist, min_time, len(points_redux)))
        return redux(points, min_dist*overshoot_factor**0.8, min_time*overshoot_factor**0.8, max_points)
    else:
        print("DEBUG: distance steps in meters: %.2f" % min_dist)
        print("DEBUG: num points: %i" % len(points_redux))
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
    points = [Point(*x) for x in data]
    return points

def main():
    summary = {}
    swing_radius = 3.01

    points = read_file()

    logging.debug(__version__)
    
    #somepoints=redux(points, 0.01, datetime.timedelta(seconds=5), 1024)
    #finnpoints=redux(points, 0.01, datetime.timedelta(seconds=5), 187)
    outliers=redux(points, 0.01, datetime.timedelta(seconds=60), 60)
    max_distance=0
    for twopoints in itertools.combinations(outliers, 2):
        distance = twopoints[0].distance_to(twopoints[1])
        if distance > max_distance:
            outliers2 = twopoints
            max_distance = distance

    outliers2[0].colour = 'g'
    outliers2[1].colour = 'g'

    midpoint = Point(0,0,colour='g', ts='1970-01-01Txxxxxx')

    midpoint.lat = sum([p.lat for p in outliers2])
    midpoint.lat /= len(twopoints)
    midpoint.long = sum([p.long for p in outliers2])
    midpoint.long /= len(twopoints)

    #import pdb; pdb.set_trace()

    finnpoints.append(midpoint)

    points[-1].colour = 'b'

    finnpoints.append(points[-1])

    print(f"DEBUG: max distance: {max_distance:.1f}")

    #finnpoints = [x for x in finnpoints if x['color'] != 'r']

    finnurl="https://kart.finn.no/?lng=10.48015&lat=59.83833&zoom=18&mapType=norortho&markers="
    finnurl+='%7C'.join([x.string for x in finnpoints])
    summary['finnurl'] = finnurl

    #print("\n".join(["{lat},{long}".format(**point) for point in points]))

    max_lat = max([point.lat for point in points])
    min_lat = min([point.lat for point in points])
    max_long = max([point.long for point in points])
    min_long = min([point.long for point in points])

    summary['distance'] = points[-1].distance_to(midpoint)
    summary['ts'] = points[-1].ts
    summary['lastpos'] = (points[-1].lat, points[-1].long)
    summary['estimated_anchorpos'] = (midpoint.lat, midpoint.long)
    summary['box'] = [[min_lat, min_long], [max_lat,max_long]]
    summary['bearing'] = midpoint.bearing(points[-1])

    if (summary['distance'] > swing_radius):
        alarm("distance to expected anchoring point is %.1f" % summary['distance'])
        alarm(finnurl)
        swing_radius = (swing_radius+summary['distance'])/2.0
    else:
        swing_radius *= 0.99999

    data = [[p.lat, p.long, p.ts] for p in points]
    redux_data = [[p.lat, p.long, p.ts] for p in somepoints]

    with open('anchoring-geojson.json', 'w') as f:
        json.dump(parser.geojson(data), f)

    with open('anchoring-geojson-redux.json', 'w') as f:
        json.dump(parser.geojson(redux_data), f)
        
    with open('anchoring-jtt.json', 'w') as f:
        json.dump(parser.jtt(data), f)

    with open('anchoring-jtt-redux.json', 'w') as f:
        json.dump(parser.jtt(redux_data), f)
        
    with open('anchoring-summary.json', 'w') as f:
        json.dump(summary, f, indent=4)

if __name__ == '__main__':
    try:
        main()
    except:
        alarm("exception in gps parsing script")
        logging.error("exception found", exc_info=True)
