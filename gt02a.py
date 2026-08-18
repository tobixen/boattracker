## Tracker GT02A dyegood version ... 2.3?

import logging
import asyncio
from point import Point, Path

class BlobError(Exception):
    def __init__(self, errtype, blobdata, position):
        self.errtype = errtype
        self.blobdata = blobdata
        self.position = position
        Exception.__init__(self)

def parse_blobs(content):
    points = Path()
    blobs = []
    junkchunks = []
    bloberrors = []
    i = content.find(b'(')
    assert i>=0
    if i:
        junkchunks.append(content[:i])
    for blob in content[i+1:].split(b'('):
        if not blob:
            continue
        i = blob.find(b')')
        if i>0:
            blobs.append(blob[:i])
        junk = blob[i+1:]
        if junk not in (b'', b'\n', b'028042516052BR00210907A5'):
            junkchunks.append(junk)

    for blob in blobs:
        try:
            point = parse_blob(blob)
            ## Apparently there is a bug now with the async read and
            ## write code, the points are not always written in the
            ## correct order to the file.  (it could also be that the
            ## timestamps from the tracker is wrong - but I rule that
            ## out since, 1) this behaviour only occurred after introducing
            ## the async code, 2) this behaviour almost only appears when doing a
            ## replay.
            if point:
                points.append(point)
                i = 1
                while len(points)>i+2 and points[-i].ts < points[-i-1].ts:
                    points[-i] = points[-i-1]
                    points[-i-1] = point
                    ## Are we sure the order is wrong, or is it the timestamp that is wrong?
                    if points[-i-2].distance_to(points[-i]) < points[-i-1].distance_to(points[-i]) and points[-i-1].distance_to(points[-i-1])>2 and points[-i-1].time_delta(points[-i]).total_seconds<120:
                        import pdb; pdb.set_trace()
                    if i%100 == 0:
                        import pdb; pdb.set_trace()
                    i += 1

        except BlobError as err:
            bloberrors.append(err)
            
    ## TODO: junkchunks should maybe be saved to disk.  It most likely only
    ## contains junk from unauthorized connection attempts

    ## TODO: bloberrors should maybe be saved to disk.  It should be analyzed, it's data from the tracker
    ## that's thrown away as we don't understand it.  Mini-analyzing from 2024-06:
    ## * 23 non-ascii blobs, most likely unauthorized connection attempts
    ## * 274 junk blobs, 24 unique, my tests + http User-Agent headers
    ## * 402 (252 unique) BZ-blobs.  Contains some data from the tracker.
    ## * 2635 "oddblobs", 994 unique.  Those are comparable with the BZ-blobs.  Should investigate.
    ## * 1 wrong ts and 2 fake news
    ## (compare that to 1152117 apparently valid points ...)
    return points

def parse_blob(blob):
    try:
        blob = blob.decode('ascii')
    except:
        raise BlobError("non-ascii blob", str(blob), 0)
    if blob.startswith('028042516052BP05355228042516052'):
        blob = blob.replace('028042516052BP05355228042516052', '028042516052BR00')
        ## TODO: we're potentially throwing away some kind of useful information from the tracker here
    if blob == '028042516052BP00355228042516052HSO199':
        ## TODO: we're potentially throwing away some kind of useful information from the tracker here
        return None
    if blob.startswith('028042516052BZ00'):
        raise BlobError("BZ-blob", blob, 0)
    if blob.startswith('028042516052BR00'):
        blob = blob[16:]
        if blob==',,01000000':
            ## TODO: we're potentially throwing away some kind of useful information from the tracker here
            return None
        if blob.startswith(',{') and blob.endswith('}\n,01000000'):
            raise BlobError("oddblob", blob, 16)
        ts = f"20{blob[0:2]}-{blob[2:4]}-{blob[4:6]}T{blob[33:39]}"
        if ts.startswith('2000-00-00'):
            raise BlobError("fake news blob", blob, 16)
        ## TODO: should either edit the raw data to deal with some out-of-order-problems
        ## or make a better hack somewhere for sorting it properly
        if ts == '2021-06-19T164341':
            raise BlobError("Wrong timestamp?", blob, 16)
        try:
            lat = int(blob[7:9])+float(blob[9:16])/60
        except:
            import pdb; pdb.set_trace()
            raise BlobError("other", blob, 16)
        if blob[16:17] == 'S':
            lat = -lat
        else:
            if blob[16:17] != 'N':
                import pdb; pdb.set_trace()
                raise BlobError('invalid latitude', blob, 16)
        try:
            long = int(blob[17:20])+float(blob[20:27])/60
            if blob[27] == 'W':
                long = -long
            else:
                assert(blob[27:28] == 'E')
        except:
            import pdb; pdb.set_trace()
        speed_noise_heading = blob[28:45]
        speed = float(blob[28:32])/3600*1000 ## return m/s rather than km/h
        ## TODO: what's with blob[32:39]?  Extra decimals to speed?
        heading = float(blob[39:45])
        more_noise = None
        if blob[45:] != '01000000L00000000':
            more_noise = blob[45:]
            logging.error("point [%.5f, %.5f, %s] - unexpected data on position 45-: %s (we're still missing altitude?)" % (lat, long, ts, blob[45:]))
        return Point(lat, long, ts, speed, heading)
        ## TODO: should investigate
        #return Point(lat, long, ts, speed, heading, blob[32:39], more_noise)
    else:
        raise BlobError("junk", blob, 0)

class Receiver:
    def __init__(self, mypos):
        self.mypos = mypos

    async def receive_blobs(self, reader, writer):
        while True:
            try:
                blob = await asyncio.wait_for(reader.readuntil(b')'), timeout=60)
                print(f"DEBUG: {blob.decode('ascii')}")
            except:
                logging.critical("exception found", exc_info=True)
                writer.close()
                break
            with open('gpstracker.raw', 'ab') as rawfile:
                rawfile.write(blob)
                rawfile.write(b'\n')
            try:
                if blob.startswith(b'(') and blob.endswith(b')'):
                    point = parse_blob(blob[1:-1])
                else:
                    logging.critical("noise found: %s" % blob)
            except:
                logging.critical("exception found", exc_info=True)
                writer.close()
                break
            if point:
                self.mypos.process_point(point)


def read_file(fn='gpstracker.raw'):
    with open(fn, 'rb') as foofile:
        content=foofile.read()
    data = parse_blobs(content)
    assert(data is not None)
    return data
