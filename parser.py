import logging

def parse_blobs(content):
    points = []
    for blob in content.split(')('):
        if blob.startswith('('):
            blob=blob[1:]
        if blob.endswith(')'):
            blob=blob[:1]
        if blob == '028042516052BP00355228042516052HSO199':
            continue
        if blob.startswith('028042516052BP'):
            logging.warning("skipping blob: %s" % blob)
        elif blob.startswith('028042516052BR00'):
            blob = blob[16:]
            ts = f"20{blob[0:2]}-{blob[2:4]}-{blob[4:6]}T{blob[33:39]}"
            if ts<'2021-06-19':
                continue
            lat = int(blob[7:9])+float(blob[9:16])/60
            if blob[16] == 'S':
                lat = -lat
            else:
                assert blob[16] == 'N'
            long = int(blob[17:20])+float(blob[20:27])/60
            if blob[27] == 'W':
                long = -long
            else:
                assert(blob[27] == 'E')
            if blob[28:32] != '000.':
                logging.error("unexpected data on position 28-33: %s (is this speed?  altitude?)" % (blob[28:33]))
            if blob[39:] != '000.0001000000L00000000':
                logging.error("unexpected data on position 39-: %s (is this speed?  altitude?)" % (blob[39:]))
            points.append([lat, long, ts])
        else:
            logging.error("unexpected blob: " + blob)
    return points

def geojson(points):
    """Takes a simple points list and returns a data set that will
    conform to the GEOJson RFC7946 format if saved through the json
    module.  (There also exists a geojson module, should eventually
    consider to use that)
    """
    points = [[points[0], points[1]] for point in points]
    data={
        'type': 'Feature',
        'geometry': {
            'type': 'LineString',
            'coordinates': points
        }
    }
    return data
    
def jtt(points, title="Anchor drift", desc="Tracking of the vessel S/Y Solveig LJ6994 while staying by anchor"):
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
                    points
                ]
            }}
        ]
    }
