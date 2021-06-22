#!/usr/bin/python

import sys

__version__ = '0.0.1'

from geopy.distance import distance as geo_distance
import itertools
import json
import logging
import requests

sys.path.append('.')

import parser
from secret import push_token

points = []
summary = {}
rope_length = 35

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

    @property
    def tuple(self): return self.lat, self.long

    @property
    def string(self): return f"{self.long:.5f},{self.lat:.5f},{self.colour},{self.ts[11:13]}"

with open('gpstracker.raw') as foofile:
    content=foofile.read()
data = parser.parse_blobs(content)
points = [Point(*x) for x in data]

def redux(points, min_dist, max_points):
    points_redux = []
    lastpoint = None
    for point in points:
        if lastpoint and lastpoint.distance_to(point)<min_dist:
            continue
        else:
            lastpoint=point
            points_redux.append(point)
    if len(points_redux)>max_points:
        overshoot_factor = len(points_redux)/max_points
        print("DEBUG: overshoot factor: %.2f.  distance: %.2f. points: %i" % (overshoot_factor, min_dist, len(points_redux)))
        return redux(points, min_dist*overshoot_factor**0.8, max_points)
    else:
        print("DEBUG: distance steps in meters: %.2f" % min_dist)
        print("DEBUG: num points: %i" % len(points_redux))
        return points_redux


def find_distance(pos1, pos2):
    return geo_distance(pos1.tuple,pos2.tuple).meters

logging.debug(__version__)
finnpoints=redux(points, 3.0, 186)


outliers=redux(finnpoints, 13, 40)
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

if (summary['distance'] > rope_length):
    alarm("distance to expected anchoring point is %.1f" % summary['distance'])
    alarm(finnurl)

with open('anchoring-geojson.json', 'w') as f:
    json.dump(parser.geojson(data), f)

with open('anchoring-jtt.json', 'w') as f:
    json.dump(parser.jtt(data), f)

with open('anchoring-summary.json', 'w') as f:
    json.dump(summary, f, indent=4)
