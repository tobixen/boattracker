# boattracker

I bought some chinese GPS tracker, installed it in my boat and got it to report positions to my server.  Now I'm doing stats on it, like pushing alarms to my cellphone if it's moved or if it the anchor drags while it's by anchor.

## Features

* Auto-detects sailing, stops, mooring and anchoring.
* Automatic anchor alarm, sends a message when the boat is leaving the anchorage or the mooring
* Makes statistics on sailing distances and stops, exports to JSON and log format (intended to be copied over to the captain's log)
* Makes a slightly compressed export of all points, in .json format.
* Web-UI with tracks

## Work in progress

My intention is to refactor and document everything in such a way that it can be used by other people than me and with other tracker solutions.  I may even prioritize it if you nag on me.

## Web interface

The web interface at https://solveig.oslo.no/BoatTracker/Boat%20Tracker.html was set up by my son.  It's included in the BoatTracker subdirectory.

## Reinventing the wheel

I'm quite sure that most of the algorithms here have already been written by others (particularly the map interface).  The rational thing to do would have been to check up what others have already done and try to stich it together.  Anyway it has been great fun making this project, 
