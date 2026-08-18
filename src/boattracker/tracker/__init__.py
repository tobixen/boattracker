"""The GPS/GSM tracker daemon: wire format, stop detection, anchor alarm.

`gt02a` parses the TK103 wire format, `point` holds the geometry and the stop/mooring
detection, `alarm` sends the notifications and `gpsparser` is the listening daemon that
ties them together.
"""
