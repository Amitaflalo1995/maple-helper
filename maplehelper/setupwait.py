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


def wait_for_setup(limit_s: float = 900, step_s: float = 0.5) -> bool:
    """Wait while an update installs (up to limit_s). True when we had to wait."""
    waited = False
    start = time.monotonic()
    told = False
    while setup_running() and time.monotonic() - start < limit_s:
        waited = True
        if not told and time.monotonic() - start > 8:
            told = True
            _tell_waiting()      # an installer window left open would otherwise mean a silent, long wait
        time.sleep(step_s)
    return waited


WAITING_TEXT = {
    "he": "Maple Helper מתעדכן או מותקן כרגע. הוא ייפתח מעצמו כשההתקנה תסתיים.",
    "en": "Maple Helper is being updated or installed right now. It opens by itself when that's done.",
}


def _tell_waiting() -> None:
    """A small note while we wait (in its own thread: the wait goes on, and ends when the setup does)."""
    if sys.platform != "win32":
        return
    import ctypes
    import threading
    lang = _language()
    flags = 0x40 | 0x10000 | (0x80000 | 0x100000 if lang == "he" else 0)   # info, foreground, RTL in Hebrew
    threading.Thread(target=lambda: ctypes.windll.user32.MessageBoxW(None, WAITING_TEXT.get(lang, WAITING_TEXT["en"]),
                                                                     "Maple Helper", flags), daemon=True).start()


DOWNLOAD_URL = "https://github.com/Amitaflalo1995/maple-helper/releases/latest/download/MapleHelper-Setup.exe"
BROKEN_TEXT = {
    "he": "חלק מהקבצים של Maple Helper חסרים או פגומים: כנראה עדכון שנקטע, או אנטי-וירוס שחסם קובץ.\n\n"
          "להתקין מחדש? ההגדרות והדמויות שלכם יישמרו.",
    "en": "Some Maple Helper files are missing or damaged (probably an interrupted update, or an antivirus "
          "blocked a file).\n\nReinstall now? Your settings and characters are kept.",
}


def _language() -> str:
    """The app's language from settings.json (standard library only: Qt may be what's missing)."""
    import json
    try:
        from .store import DATA_DIR
        return json.loads((DATA_DIR / "settings.json").read_text(encoding="utf-8")).get("language") or "he"
    except Exception:
        return "he"


def report_broken_install(exc: BaseException) -> None:
    """A frozen build that can't import its own modules (a file is missing): explain and offer a reinstall,
    instead of PyInstaller's bare traceback window. Standard library only: Qt itself may be what's missing."""
    import traceback
    try:
        from .store import DATA_DIR
        logs = DATA_DIR / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        (logs / "startup-error.log").write_text("".join(traceback.format_exception(exc)), encoding="utf-8")
    except Exception:
        pass
    if sys.platform != "win32":
        return
    import ctypes
    MB_YESNO, MB_ICONERROR, MB_SETFOREGROUND, IDYES = 0x4, 0x10, 0x10000, 6
    MB_RIGHT, MB_RTLREADING = 0x80000, 0x100000
    lang = _language()
    # one language per box: Hebrew in a left-to-right box came out scrambled (seen in testing)
    flags = MB_YESNO | MB_ICONERROR | MB_SETFOREGROUND | (MB_RIGHT | MB_RTLREADING if lang == "he" else 0)
    answer = ctypes.windll.user32.MessageBoxW(None, BROKEN_TEXT.get(lang, BROKEN_TEXT["en"]), "Maple Helper", flags)
    if answer != IDYES:
        return
    # the update that broke it is usually still downloaded (and was checksum-verified then): run it again
    try:
        from .store import DATA_DIR
        cached = sorted((DATA_DIR / "updates").glob("MapleHelper-Setup-*.exe"), key=lambda f: f.stat().st_mtime)
    except Exception:
        cached = []
    if cached:
        import subprocess
        try:
            subprocess.Popen([str(cached[-1])], close_fds=True)
            return
        except OSError:
            pass
    import webbrowser
    webbrowser.open(DOWNLOAD_URL)
