"""Maple Helper entry point: tray icon, global hotkeys, overlay, voice, onboarding."""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import sys
import threading
import winreg
from pathlib import Path

from PySide6.QtCore import QAbstractNativeEventFilter, QLockFile, QTimer
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon, QWidget

from . import APP_NAME, __version__, claude_setup, updater, winapi
from .brain import Brain
from .i18n import I18n
from .kb import KnowledgeBase
from .store import ASSETS, DATA_DIR, History, Profiles, Settings
from .ui import theme
from .ui.dialogs import Onboarding, SettingsDialog
from .ui.overlay import Overlay
from .ui.toast import notify
from .voice import VoiceController

HOTKEY_TOGGLE = 1
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


class HotkeyFilter(QAbstractNativeEventFilter):
    def __init__(self, on_hotkey):
        super().__init__()
        self.on_hotkey = on_hotkey

    def nativeEventFilter(self, event_type, message):
        if event_type == b"windows_generic_MSG":
            msg = wt.MSG.from_address(int(message))
            if msg.message == winapi.WM_HOTKEY:
                self.on_hotkey(msg.wParam)
                return True, 0
        return False, 0


class MapleHelperApp:
    def __init__(self, qapp: QApplication):
        self.qapp = qapp
        self.settings = Settings()
        self.profiles = Profiles()
        self.kb = KnowledgeBase()
        self.font_family = theme.load_fonts()
        theme.FONT_FAMILY = self.font_family
        qapp.setWindowIcon(QIcon(str(ASSETS / "brand" / "app.ico")))
        qapp.setQuitOnLastWindowClosed(False)

    # ------------------------------------------------------------------ startup

    def style(self, opacity: float | None = None) -> str:
        theme.set_mode(self.settings["appearance"])
        return theme.stylesheet(self.font_family, self.settings["font_size"],
                                self.settings["opacity"] if opacity is None else opacity)

    def run_onboarding(self) -> bool:
        first = True
        while True:
            dlg = Onboarding(self.settings, self.profiles, self.kb, self.style)
            if not first:
                dlg.restart_on_language()
            r = dlg.exec()
            if r == Onboarding.RESTART:
                first = False
                continue
            return bool(r)

    def start(self) -> bool:
        if not self.settings["onboarding_done"] or not self.profiles.active:
            if not self.run_onboarding():
                return False
        api_key = claude_setup.load_api_key() if self.settings["api_key_fallback"] else None
        self.brain = Brain(self.kb, model=self.settings["model"], length=self.settings["answer_length"], api_key=api_key)
        self.overlay = Overlay(self.settings, self.profiles, self.kb, self.brain)
        self.overlay.setStyleSheet(self.style())
        self.overlay.setWindowOpacity(1.0)
        self.overlay.settings_requested.connect(self.open_settings)
        self.overlay.profile_requested.connect(self.open_settings)

        # hotkeys live on a hidden native window
        self.hotkey_host = QWidget()
        self.hotkey_host.winId()
        self.filter = HotkeyFilter(self.on_hotkey)
        self.qapp.installNativeEventFilter(self.filter)
        self.register_hotkeys()

        self.voice = VoiceController(self.settings["hotkey_voice"])
        self.voice.started.connect(self.on_voice_start)
        self.voice.state.connect(lambda s: self.overlay.voice_state(s))
        self.voice.text.connect(self.on_voice_text)

        self.make_tray()
        self.apply_autostart()
        QTimer.singleShot(4000, self.check_kb_update_silently)
        t = I18n(self.settings["language"])
        self.toast(t("app_tagline"), t("ob_done_hint").replace("F9", self.settings["hotkey_toggle"]))
        self.qapp.aboutToQuit.connect(self.shutdown)
        return True

    def register_hotkeys(self):
        hwnd = int(self.hotkey_host.winId())
        winapi.unregister_hotkey(hwnd, HOTKEY_TOGGLE)
        key = self.settings["hotkey_toggle"]
        if not winapi.register_hotkey(hwnd, HOTKEY_TOGGLE, key):
            t = I18n(self.settings["language"])
            self.toast(t("settings"), t("hotkey_taken", key=key), timeout_ms=9000)

    def toast(self, title: str, message: str = "", timeout_ms: int = 5000):
        notify(title, message, rtl=I18n(self.settings["language"]).rtl, font_family=self.font_family,
               timeout_ms=timeout_ms)

    # ------------------------------------------------------------------ events

    def capture(self, hwnd):
        return winapi.capture_game(hwnd)

    def on_hotkey(self, hotkey_id: int):
        if hotkey_id == HOTKEY_TOGGLE:
            if self.overlay.isVisible():
                self.overlay.close_overlay()
                self.maybe_summarize_later()
            else:
                self.overlay.toggle(self.capture)

    def on_voice_start(self):
        # holding the voice key in game opens the chat (with a fresh screenshot)
        if not self.overlay.isVisible():
            self.overlay.toggle(self.capture)

    def on_voice_text(self, text: str):
        fixed = self.kb.resolve_names(text)
        self.overlay.voice_text(fixed, send=self.settings["voice_send_immediately"])

    def maybe_summarize_later(self):
        """After 30 minutes without the chat, the session is summarized for long-term context."""
        if not hasattr(self, "_idle_timer"):
            self._idle_timer = QTimer(singleShot=True, interval=30 * 60 * 1000, timeout=self.summarize_session)
        self._idle_timer.start()

    def summarize_session(self):
        if self.overlay.isVisible():
            return
        transcript = self.overlay.end_session()
        c = self.profiles.active
        if not transcript or not c:
            return

        def work():
            s = self.brain.summarize(transcript)
            if s:
                History(c.id).add_summary(s)
        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------------------ tray & settings

    def make_tray(self):
        t = I18n(self.settings["language"])
        self.tray = QSystemTrayIcon(QIcon(str(ASSETS / "brand" / "app.ico")))
        self.tray.setToolTip(f"{APP_NAME} · {t('app_tagline')}")
        menu = QMenu()
        a_show = QAction(t("tray_show"), menu, triggered=lambda: self.overlay.toggle(self.capture))
        a_set = QAction(t("tray_settings"), menu, triggered=self.open_settings)
        a_quit = QAction(t("tray_quit"), menu, triggered=self.qapp.quit)
        for a in (a_show, a_set, a_quit):
            menu.addAction(a)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda r: self.overlay.toggle(self.capture)
                                    if r == QSystemTrayIcon.Trigger else None)
        self.tray.show()
        self._tray_menu = menu

    def open_settings(self):
        dlg = SettingsDialog(self.settings, self.profiles, self.kb, self.style)
        dlg.changed.connect(self.on_settings_changed)
        dlg.update_kb_requested.connect(self.update_kb_interactive)
        dlg.exec()
        self.overlay.refresh_profile_chip()

    def on_settings_changed(self):
        self.overlay.apply_language()
        self.overlay.setStyleSheet(self.style())
        self.overlay.apply_capture_mode()
        self.brain.length = self.settings["answer_length"]
        self.voice.set_key(self.settings["hotkey_voice"])
        self.register_hotkeys()
        self.apply_autostart()
        self.tray.hide()
        self.make_tray()

    def apply_autostart(self):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
                if self.settings["start_with_windows"]:
                    exe = sys.executable if getattr(sys, "frozen", False) else f'"{sys.executable}" -m maplehelper'
                    winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, exe)
                else:
                    try:
                        winreg.DeleteValue(k, APP_NAME)
                    except FileNotFoundError:
                        pass
        except OSError:
            pass

    # ------------------------------------------------------------------ knowledge base updates

    def check_kb_update_silently(self):
        self.pending_installer = None
        if getattr(sys, "frozen", False):
            def app_update():
                path = updater.download_app_update(__version__)
                if path:
                    self.pending_installer = path
                    QTimer.singleShot(0, lambda: self.toast(I18n(self.settings["language"])("update_ready")))
            threading.Thread(target=app_update, daemon=True).start()

        def work():
            if updater.update_kb():
                QTimer.singleShot(0, self.reload_kb)
                QTimer.singleShot(0, lambda: self.toast(I18n(self.settings["language"])("kb_updated")))
        threading.Thread(target=work, daemon=True).start()

    def update_kb_interactive(self):
        t = I18n(self.settings["language"])
        changed = updater.update_kb()
        if changed:
            self.reload_kb()
        self.toast(t("kb_updated") if changed else t("kb_uptodate"))

    def reload_kb(self):
        self.kb = KnowledgeBase()
        self.brain.kb = self.kb
        self.overlay.kb = self.kb

    def shutdown(self):
        try:
            winapi.unregister_hotkey(int(self.hotkey_host.winId()), HOTKEY_TOGGLE)
        except Exception:
            pass
        if getattr(self, "pending_installer", None):
            updater.run_installer_silently(self.pending_installer)


APP_ID = "MapleHelper.App"


def selftest(out_path: str) -> int:
    """`Maple Helper.exe --selftest <file>`: checks every component loads in the packaged build."""
    import json
    import traceback
    report = {}
    for name, fn in {
        "voice": lambda: __import__("faster_whisper") and "ok",
        "ctranslate2": lambda: __import__("ctranslate2").__version__,
        "audio": lambda: str(__import__("sounddevice").query_devices(kind="input")["name"]),
        "claude": lambda: __import__("maplehelper.brain", fromlist=["find_claude"]).find_claude(),
        "kb": lambda: len(KnowledgeBase().entities),
        "assets": lambda: (ASSETS / "brand" / "app.ico").exists(),
    }.items():
        try:
            report[name] = fn()
        except Exception:
            report[name] = "ERROR " + traceback.format_exc(limit=2)
    Path(out_path).write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    return 0


def main():
    if len(sys.argv) > 2 and sys.argv[1] == "--selftest":
        return selftest(sys.argv[2])
    # Windows shows this identity (not "Python") for the taskbar and notifications
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    qapp = QApplication(sys.argv)
    qapp.setStyle("Fusion")   # the native Windows 11 style ignores rounded corners on buttons
    qapp.setApplicationName(APP_NAME)
    qapp.setApplicationDisplayName(APP_NAME)
    lock = QLockFile(str(DATA_DIR / "app.lock"))
    if not lock.tryLock(100):
        return 0  # already running
    app = MapleHelperApp(qapp)
    if not app.start():
        return 0
    return qapp.exec()


if __name__ == "__main__":
    sys.exit(main())
