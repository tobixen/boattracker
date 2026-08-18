## very inefficient algorithm as for now - should consider improving it if needed

import re  ## we should probably have considered to use some xml-parsing python module, but ... nah, make it simple stupid as for now

from boattracker.tracker.point import Point


def _split(gpx_data, pos=1):
    trkptpos = gpx_data.find('<trkpt', pos)
    return(gpx_data[:trkptpos], gpx_data[trkptpos:])

split_header = lambda gpx_data: _split(gpx_data, 0)
split_trkpt = _split

def parse_trkpt(trkpt):
    ## may throw an ugly traceback if the trkpt does not contain a track point
    attribs = re.search('<trkpt([^]]*)>', trkpt).group(1)
    lon = float(re.search('lon="([^\"]*)"', attribs).group(1))
    lat = float(re.search('lat="([^\"]*)"', attribs).group(1))
    return Point(lat, lon)

def split_to_point(gpx_data, target, acceptable_distance1=5, acceptable_distance2=150, keep=True, inject=None):
    ## TODO: consider heading, too
    header,rest = split_header(gpx_data)
    rolled_past = [header]
    prev_distance=999999
    while True:
        trkpt, rest = split_trkpt(rest)
        point = parse_trkpt(trkpt)
        if keep:
            rolled_past.append(trkpt)
        distance = point.distance_to(target)
        if distance < acceptable_distance1 or (prev_distance<acceptable_distance2 and distance>prev_distance):
            if inject:
                rolled_past.append(inject.gpx_trkpt())
            rolled_past.append("</trkseg></trk></gpx>")
            return ("".join(rolled_past), header + rest)
        prev_distance = distance

def find_gap(gpx_data, gap, acceptable_distance2):
    tmppos = []
    pos1 = Point(*gap['jump_from'])
    pos2 = Point(*gap['jump_to'])
    (dummy, rest) = split_to_point(gpx_data, pos1, acceptable_distance2=acceptable_distance2,  keep=False)
    return split_to_point(rest, pos2, acceptable_distance2=acceptable_distance2, keep=True, inject=pos2)
