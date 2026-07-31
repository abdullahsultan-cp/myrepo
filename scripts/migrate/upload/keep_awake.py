#!/usr/bin/env python3
"""keep_awake.py — stop Windows sleeping while a long migration runs.

powercfg changes the timeouts, but a lid close or an idle policy can still
suspend the machine. This asks Windows directly to treat the system as busy for
as long as the process lives, which is the same mechanism a video player uses.

Ctrl-C, or just close the window, to release it.
"""
import ctypes
import time

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001

flags = ES_CONTINUOUS | ES_SYSTEM_REQUIRED
if ctypes.windll.kernel32.SetThreadExecutionState(flags) == 0:
    raise SystemExit("  could not set the execution state")

print("  keeping this machine awake. Close this window to release.")
try:
    while True:
        # Re-assert periodically: some policies reset the request.
        ctypes.windll.kernel32.SetThreadExecutionState(flags)
        time.sleep(60)
except KeyboardInterrupt:
    pass
finally:
    ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
    print("  released; normal sleep behaviour restored.")
