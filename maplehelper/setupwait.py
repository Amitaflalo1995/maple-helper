"""Windows: never start while an update is being installed.

The installer holds the "MapleHelperSetup" mutex (SetupMutex in packaging/installer.iss). Starting the app
then loads DLLs (Qt, numpy) the installer is about to replace; it can't, gives up halfway and leaves a
half-updated install. This runs before anything heavy is imported (standard library only), so it must stay
the first thing the launchers do.
"""
from __future__ import annotations

import sys
import time

SETUP_MUTEX = "MapleHelperSetup"
SYNCHRONIZE = 0x00100000


def setup_running() -> bool:
    if sys.platform != "win32":
        return False
    import ctypes
    k32 = ctypes.windll.kernel32
    h = k32.OpenMutexW(SYNCHRONIZE, False, SETUP_MUTEX)
    if not h:
        return False
    k32.CloseHandle(h)
    return True


def wait_for_setup(limit_s: float = 180, step_s: float = 0.5) -> bool:
    """Wait while an update installs (up to limit_s). True when we had to wait."""
    waited = False
    end = time.monotonic() + limit_s
    while setup_running() and time.monotonic() < end:
        waited = True
        time.sleep(step_s)
    return waited
