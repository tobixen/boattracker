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

__version__ = '0.0.3'

import sys
import asyncio
import itertools
import json
import logging
import requests
import datetime
import subprocess
import socket

sys.path.append('.')

import parser
from point import Point, Path, BoatPosData
import gt02a
from alarm import alarm

async def receive_data(reader, writer):
    await gt02a.receive_blobs(reader, writer, mypos)

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

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except:
        #alarm("exception in gps parsing script")
        logging.error("exception found", exc_info=True)
