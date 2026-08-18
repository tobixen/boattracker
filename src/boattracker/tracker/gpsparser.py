#!/usr/bin/python

### Toughts for refactoring
### * We need test code before it can be refactored

### Thoughts for daemonizing it
### * Listener for receiving data
### * Hard-coded parser object for turning the data into Points
### * Data split into "archived" and "current", but everything stays in memory as for now
### * One iteration every time data is received
### * On every iteration, the files are written in full to disk.  Considered "cheap enough" as for now.
### * Push actions
### * "Current" data is reprocessed on every iteration

import asyncio
import logging

from boattracker.tracker import gt02a
from boattracker.tracker.point import BoatPosData


async def main(start_server=True, test_mode=False):
    if not test_mode:
        mypos = gt02a.read_file().split()
        mypos.big_processes(force=True)
    else:
        mypos = BoatPosData()

    if start_server:
        receiver = gt02a.Receiver(mypos)
        server = await asyncio.start_server(
            receiver.receive_blobs, '*', 6666)

    addrs = ', '.join(str(sock.getsockname()) for sock in server.sockets)
    print(f'Serving on {addrs}')

    async with server:
        await server.serve_forever()

def run():
    """Console entry point (`boattracker-daemon`): run the server until it dies.

    The daemon is meant to stay up unattended, so an exception is logged with its
    traceback rather than printed to a terminal nobody is watching.
    """
    try:
        asyncio.run(main())
    except Exception:
        #alarm("exception in gps parsing script")
        logging.error("exception found", exc_info=True)


if __name__ == '__main__':
    run()
