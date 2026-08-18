import subprocess
import socket
import time

enable = True

last_msg=[0,4]

def alarm(msg, level=2):
    lvltxt={0: 'OK', 1: 'WARNING', 2: 'CRITICAL', 3: 'UNKNOWN'}
    local_enable = enable
    if last_msg[1] == level and time.time()-last_msg[0]<3600:
        local_enable = False
    if local_enable:
        last_msg[0] = time.time()
        last_msg[1] = level
        subprocess.run(["/usr/bin/sudo", "/usr/local/sbin/send_nsca", f"PROCESS_SERVICE_CHECK_RESULT;{socket.gethostname()};Solveig may be drifting;{level};{lvltxt[level]}: {msg}"])
    print(f"ALARM: {lvltxt[level]}: {msg} (sent: {local_enable})")


