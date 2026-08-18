"""Send an alarm, via NSCA to a monitoring host, and to the terminal.

The service description carried the boat's name until 2026-08-18. It is
`[daemon] alarm_service` now, falling back to a generic phrase rather than to one
particular boat - the daemon has to run for anybody, and with nothing configured.
"""

import socket
import subprocess
import time

from boattracker import config

enable = True

last_msg=[0,4]

def service():
    """The NSCA service description this reports against."""
    name = config.get('BOAT_NAME')
    return config.get('ALARM_SERVICE') or f"{name or 'Boat'} may be drifting"


def alarm(msg, level=2):
    lvltxt={0: 'OK', 1: 'WARNING', 2: 'CRITICAL', 3: 'UNKNOWN'}
    local_enable = enable
    if last_msg[1] == level and time.time()-last_msg[0]<3600:
        local_enable = False
    if local_enable:
        last_msg[0] = time.time()
        last_msg[1] = level
        subprocess.run(["/usr/bin/sudo", "/usr/local/sbin/send_nsca", f"PROCESS_SERVICE_CHECK_RESULT;{socket.gethostname()};{service()};{level};{lvltxt[level]}: {msg}"])
    print(f"ALARM: {lvltxt[level]}: {msg} (sent: {local_enable})")
