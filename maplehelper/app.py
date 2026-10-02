"""Maple Helper entry point: tray icon, global hotkeys, overlay, voice, onboarding."""
from __future__ import annotations

import sys
import threading
import webbrowser

from PySide6.QtCore import QLockFile, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QIcon, QKeySequence
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from . import APP_NAME, __version__, osapi, providers, report, telemetry, updater, whatsnew, wishlist
from .brain import Brain
from .i18n import I18n
from .kb import KnowledgeBase
from .store import ASSETS, DATA_DIR, History, Profiles, Settings
from .ui import theme
from .ui.dialogs import Onboarding, SettingsDialog
from .ui.overlay import Overlay
from .ui.patchnotes import PatchNotesDialog, WhatsNewDialog, summary
from .ui.toast import notify
from .voice import VoiceController

HOTKEY_TOGGLE = 1
HOTKEY_VOICE = 2
BACKGROUND_ARG = "--background"   # start in the tray only (autostart at login, silent updates)
UPDATED_ARG = "--updated"         # the installer reopens the app with it after "Update now": show what's new
# the .ico carries every Windows size; macOS draws the menu bar and Dock from a PNG
APP_ICON = "app.ico" if sys.platform == "win32" else "icon-256.png"


class _MainThread(QObject):
    """Background checks emit here; Qt delivers the call on the GUI thread (queued connection).

    QTimer.singleShot(0, fn) from a plain Python thread never fires: that thread has no Qt event loop.
    """
    call = Signal(object)

    def __init__(self):
        super().__init__()
        self.call.connect(lambda fn: fn())


class MapleHelperApp:
    def __init__(self, qapp: QApplication):
        self.qapp = qapp
        self.settings = Settings()
        self.profiles = Profiles()
        self.kb = KnowledgeBase()
        self.font_family = theme.load_fonts()
        theme.FONT_FAMILY = self.font_family
        qapp.setWindowIcon(QIcon(str(ASSETS / "brand" / APP_ICON)))
        qapp.setQuitOnLastWindowClosed(False)
        self.main_thread = _MainThread()

    # ------------------------------------------------------------------ startup

    def style(self, opacity: float | None = None) -> str:
        theme.set_mode(self.settings["appearance"])
        self.qapp.setLayoutDirection(Qt.RightToLeft if I18n(self.settings["language"]).rtl else Qt.LeftToRight)
        css = theme.stylesheet(self.font_family, self.settings["font_size"])
        self.qapp.setStyleSheet(css)
        return css

    @staticmethod
    def bring_dialogs_forward():
        # a macOS menu bar app is never frontmost by itself, so its dialogs would open behind the game
        if osapi.IS_MAC:
            osapi.activate_self(0)

    def run_onboarding(self) -> bool:
        first = True
        while True:
            dlg = Onboarding(self.settings, self.profiles, self.kb, self.style)
            dlg.report_requested.connect(self.make_report)
            if not first:
                dlg.restart_on_language()
            self.bring_dialogs_forward()
            r = dlg.exec()
            if r == Onboarding.RESTART:
                first = False
                continue
            return bool(r)

    def start(self) -> bool:
        fresh_install = not self.settings["onboarding_done"]
        if not self.settings["onboarding_done"]:
            if not self.run_onboarding():
                return False
        elif not self.profiles.active:
            # set up already (language, AI): only a character is missing
            self.style()
            Onboarding(self.settings, self.profiles, self.kb, self.style, only_character=True).exec()
        telemetry.init(self.settings, __version__)
        telemetry.track("app_started", fresh_install=fresh_install, background=BACKGROUND_ARG in sys.argv[1:],
                        provider=self.settings["provider"], language=self.settings["language"])
        self.brain = Brain(self.kb, provider=self.settings["provider"], length=self.settings["answer_length"])
        self.apply_ai_settings()
        threading.Thread(target=self.brain.prewarm, daemon=True).start()   # first answer without startup delay
        self.overlay = Overlay(self.settings, self.profiles, self.kb, self.brain)
        self.overlay.setStyleSheet(self.style())
        self.overlay.setWindowOpacity(1.0)
        self.overlay.shot_provider = self.capture
        self.overlay.settings_requested.connect(self.open_settings)
        self.overlay.saver_requested.connect(self.turn_on_saver)
        self.overlay.show_saver_badge(self.settings["saver_mode"])
        self.overlay.wishlist_requested.connect(self.show_wishlist)
        self.overlay.history_requested.connect(self.show_history)
        self.overlay.guides_requested.connect(lambda: self.show_guides())
        self.overlay.guide_requested.connect(lambda key: self.show_guides(key))
        self.overlay.closed.connect(self.maybe_summarize_later)
        self.overlay.update_requested.connect(self.update_now)
        self.overlay.profile_requested.connect(self.open_settings)
        self.overlay.add_character_requested.connect(self.add_character)
        self.overlay.edit_character_requested.connect(self.edit_character)
        self.overlay.delete_character_requested.connect(self.delete_character)
        # play tools: the EXP meter lives as long as the app (the window may close in between)
        self.exp_meter: dict = {}
        self.overlay.tools_requested.connect(lambda: self.show_tools())
        self.overlay.profile_changed.connect(self.on_profile_changed)
        self.overlay.sync_finished.connect(lambda ok: self._tools_call("sync_done", ok))

        self.hotkeys = osapi.Hotkeys()
        self.hotkeys.pressed.connect(self.on_hotkey)
        self.register_hotkeys()

        self.voice = VoiceController(self.settings["hotkey_voice"])
        self.register_voice_hotkey()
        self.voice.started.connect(self.on_voice_start)
        self.voice.state.connect(lambda s: self.overlay.voice_state(s))
        self.voice.text.connect(self.on_voice_text)
        self.voice.text.connect(lambda _: telemetry.track("voice_used"))
        self.overlay.mic_clicked.connect(self.voice.toggle)

        self.make_tray()
        self.apply_autostart()
        self.pending_installer = None
        self._reopen_after_update = False
        QTimer.singleShot(4000, self.check_kb_update_silently)
        QTimer.singleShot(6000, self.voice.preload)    # voice answers right away after a start or an update
        QTimer.singleShot(8000, updater.remove_old_installers)
        # a session can run for hours: look again every 3 hours
        self._update_timer = QTimer(interval=3 * 60 * 60 * 1000, timeout=self.check_kb_update_silently)
        self._update_timer.start()
        if BACKGROUND_ARG in sys.argv[1:]:
            # started with Windows or by a silent update: stay in the tray until the player asks for the chat
            t = I18n(self.settings["language"])
            self.toast(t("app_tagline"), t("ob_done_hint").replace("F9", self.settings["hotkey_toggle"]))
        else:
            QTimer.singleShot(0, lambda: self.overlay.toggle(self.capture))
        QTimer.singleShot(1500, self.check_permissions)
        self.announce_whats_new(fresh_install)
        self.qapp.aboutToQuit.connect(self.shutdown)
        return True

    def announce_whats_new(self, fresh_install: bool):
        """First start after an app update: a note in the chat with a "What's new?" button."""
        seen = self.settings["seen_version"] or ("" if fresh_install else whatsnew.FIRST_TRACKED)
        self.settings["seen_version"] = __version__
        if fresh_install:
            return            # a new player gets the welcome screen, not a changelog
        if seen != __version__:
            telemetry.track("app_updated", from_version=seen)
        notes = whatsnew.since(seen, __version__)
        if notes:
            self.overlay.add_notice(lambda t: t("whats_new_notice", version=__version__), lambda t: t("whats_new_show"),
                                    lambda: self.show_whats_new(notes))
            if UPDATED_ARG in sys.argv:
                # back from "Update now": the chat is open, show what changed right away
                QTimer.singleShot(900, lambda: self.show_whats_new(notes))

    def open_window(self, kind: str, make, on_close=None):
        """Settings, guides, history…: a window NEXT TO the chat, which stays usable (not modal).
        One window of each kind; asking again brings the open one forward."""
        windows = self.__dict__.setdefault("_windows", {})
        dlg = windows.get(kind)
        if dlg is not None and dlg.isVisible():
            dlg.raise_()
            dlg.activateWindow()
            return dlg
        dlg = make()
        windows[kind] = dlg
        dlg.setWindowModality(Qt.NonModal)
        dlg.setAttribute(Qt.WA_DeleteOnClose)                  # closed windows don't pile up in memory
        dlg.setWindowFlag(Qt.WindowStaysOnTopHint, True)      # over the game, like the chat
        dlg.finished.connect(lambda *_: windows.pop(kind, None) if windows.get(kind) is dlg else None)
        if on_close:
            dlg.finished.connect(lambda *_: on_close())
        self.bring_dialogs_forward()
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()
        return dlg

    def show_whats_new(self, notes: list[dict] | None = None):
        self.open_window("whats_new", lambda: WhatsNewDialog(
            notes if notes is not None else whatsnew.load()[:6], self.settings["language"], self.style()))

    def register_hotkeys(self):
        key = self.settings["hotkey_toggle"]
        if not self.hotkeys.register(HOTKEY_TOGGLE, key):
            t = I18n(self.settings["language"])
            self.toast(t("settings"), t("hotkey_taken", key=key), timeout_ms=9000)

    def register_voice_hotkey(self):
        self.hotkeys.unregister(HOTKEY_VOICE)
        key = self.settings["hotkey_voice"]
        if key != self.settings["hotkey_toggle"] and not self.hotkeys.register(HOTKEY_VOICE, key):
            t = I18n(self.settings["language"])
            self.toast(t("settings"), t("hotkey_taken", key=key), timeout_ms=9000)

    def check_permissions(self):
        """macOS: ask once for Screen Recording (the screenshot), and say how to grant it when missing."""
        if osapi.missing_permissions(request=True):
            t = I18n(self.settings["language"])
            self.toast(t("perm_title"), t("perm_screen_body"), timeout_ms=20000)

    def toast(self, title: str, message: str = "", timeout_ms: int = 5000):
        notify(title, message, rtl=I18n(self.settings["language"]).rtl, font_family=self.font_family,
               timeout_ms=timeout_ms)

    # ------------------------------------------------------------------ events

    def capture(self, hwnd):
        return osapi.capture_game(hwnd)

    def on_hotkey(self, hotkey_id: int):
        if hotkey_id == HOTKEY_TOGGLE:
            if self.overlay.isVisible():
                self.overlay.close_overlay()
            else:
                self.overlay.toggle(self.capture)   # also restores from the minimized bubble
        elif hotkey_id == HOTKEY_VOICE:
            self.voice.toggle()

    def on_voice_start(self):
        # the talk key in game opens the chat (with a fresh screenshot)
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
        self.tray = QSystemTrayIcon(QIcon(str(ASSETS / "brand" / APP_ICON)))
        self.tray.setToolTip(f"{APP_NAME} · {t('app_tagline')}")
        menu = QMenu()
        # rounded, app-styled menu (the app-wide stylesheet paints it; the window must be see-through at the corners)
        menu.setWindowFlags(menu.windowFlags() | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        menu.setAttribute(Qt.WA_TranslucentBackground)
        menu.setLayoutDirection(Qt.RightToLeft if t.rtl else Qt.LeftToRight)
        header = QAction(APP_NAME, menu)
        header.setEnabled(False)
        menu.addAction(header)
        menu.addSeparator()
        key = self.settings["hotkey_toggle"]
        a_show = QAction(t("tray_open"), menu, triggered=lambda: self.overlay.toggle(self.capture))
        a_show.setShortcut(QKeySequence(key))          # shown in the menu's shortcut column
        a_show.setShortcutVisibleInContextMenu(True)
        a_set = QAction(t("tray_settings"), menu, triggered=self.open_settings)
        a_quit = QAction(t("tray_quit"), menu, triggered=self.qapp.quit)
        menu.addAction(a_show)
        menu.addAction(a_set)
        if getattr(self, "pending_installer", None):
            a_upd = QAction(t("update_now_tray", version=updater.installer_version(self.pending_installer)), menu,
                            triggered=self.update_now)
            menu.addAction(a_upd)
        menu.addSeparator()
        menu.addAction(a_quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda r: self.overlay.toggle(self.capture)
                                    if r == QSystemTrayIcon.Trigger else None)
        self.tray.show()
        self._tray_menu = menu

    def open_settings(self):
        def make():
            dlg = SettingsDialog(self.settings, self.profiles, self.kb, self.style)
            dlg.changed.connect(self.on_settings_changed)
            dlg.update_kb_requested.connect(self.update_kb_interactive)
            dlg.history_cleared.connect(self.on_history_cleared)
            dlg.report_requested.connect(self.make_report)
            dlg.account_changed.connect(self.on_account_changed)
            dlg.patch_notes_requested.connect(lambda: self.show_patch_notes())
            dlg.whats_new_requested.connect(lambda: self.show_whats_new())
            return dlg
        self.open_window("settings", make, on_close=self.overlay.refresh_profile_chip)

    def add_character(self):
        before = self.profiles.active_id
        if Onboarding(self.settings, self.profiles, self.kb, self.style, only_character=True).exec():
            self.overlay.refresh_profile_chip()
            c = self.profiles.active
            if c and c.id != before:
                self.overlay.add_system(I18n(self.settings["language"])("switched_character", name=c.name))

    def edit_character(self, cid: str):
        if Onboarding(self.settings, self.profiles, self.kb, self.style, edit_id=cid).exec():
            self.overlay.refresh_profile_chip()
            self.overlay.refresh_plan()
            self.on_profile_changed()

    def delete_character(self, cid: str):
        from .ui.dialogs import ConfirmDialog
        c = next((c for c in self.profiles.characters if c.id == cid), None)
        if not c:
            return
        t = I18n(self.settings["language"])
        if not ConfirmDialog(t("delete_character"), t("delete_character_confirm", name=c.name), t("delete"),
                             t("cancel"), t.rtl, self.style()).exec():
            return
        self.profiles.remove(cid)
        if not self.profiles.characters:
            # advice needs a character: offer to create one right away
            Onboarding(self.settings, self.profiles, self.kb, self.style, only_character=True).exec()
        self.overlay.clear_feed()
        self.overlay.refresh_profile_chip()
        self.overlay.refresh_plan()
        now = self.profiles.active
        if now:
            self.overlay.add_system(t("switched_character", name=now.name))
        self.on_profile_changed()

    def apply_ai_settings(self):
        """Point the brain at the chosen provider, with its model, saver mode and (when used) its stored API key."""
        self.brain.provider = self.settings["provider"]
        ai = providers.get(self.settings["provider"])
        self.brain.api_key = ai.load_api_key() if self.settings.api_key_mode(ai.name) else None
        self.apply_saver_mode()

    def on_account_changed(self):
        # another provider or account: a warm process started under the old one is replaced
        self.apply_ai_settings()
        self.brain.shutdown()
        threading.Thread(target=self.brain.prewarm, daemon=True).start()

    def make_report(self):
        """Zip the log and diagnostics onto the desktop and show the file, ready to send."""
        import subprocess
        from pathlib import Path
        from PySide6.QtCore import QStandardPaths
        t = I18n(self.settings["language"])
        ai = providers.get(self.settings["provider"])
        info = report.system_info(__version__, updater.local_version(), f"{ai.label}: {ai.status()}")
        desktop = Path(QStandardPaths.writableLocation(QStandardPaths.DesktopLocation) or Path.home())
        path = report.build_report(desktop, info, dict(self.settings.data))
        report.log.info("problem report written: %s", path.name)
        # show the file, selected, in Explorer / Finder
        subprocess.Popen(["explorer", "/select,", str(path)] if sys.platform == "win32" else ["open", "-R", str(path)])
        self.toast(t("report_saved"), t("report_saved_body", name=path.name), timeout_ms=12000)

    def on_history_cleared(self):
        self.overlay.clear_feed()
        self.toast(I18n(self.settings["language"])("history_cleared"))

    def apply_saver_mode(self):
        """Saver mode: short answers, on the provider's lighter model when it has one.

        The warm process is respawned on the next prewarm."""
        ai = providers.get(self.settings["provider"])
        saver = self.settings["saver_mode"]
        self.brain.model = (saver and ai.saver_model) or self.settings[ai.model_setting]
        self.brain.length = "short" if saver else self.settings["answer_length"]

    def turn_on_saver(self):
        self.settings["saver_mode"] = True
        settings_win = self.__dict__.get("_windows", {}).get("settings")
        if settings_win is not None and hasattr(settings_win, "saver"):
            settings_win.saver.setChecked(True)     # its Save must not switch it off again
        self.apply_saver_mode()
        self.overlay.show_saver_badge(True)
        self.overlay.add_system(I18n(self.settings["language"])("saver_turned_on"))
        threading.Thread(target=self.brain.prewarm, daemon=True).start()

    def on_settings_changed(self):
        telemetry.set_enabled(self.settings["telemetry"])
        self.overlay.apply_language()
        self.overlay.setStyleSheet(self.style())
        self.overlay.apply_capture_mode()
        self.apply_saver_mode()
        self.overlay.show_saver_badge(self.settings["saver_mode"])
        threading.Thread(target=self.brain.prewarm, daemon=True).start()
        self.voice.set_key(self.settings["hotkey_voice"])
        self.hotkeys.unregister(HOTKEY_TOGGLE)      # free both first: a swap would otherwise collide
        self.hotkeys.unregister(HOTKEY_VOICE)
        self.register_hotkeys()
        self.register_voice_hotkey()
        self.apply_autostart()
        self.tray.hide()
        self.make_tray()

    def apply_autostart(self):
        # the setting means "start at login" on macOS (named before macOS support)
        osapi.set_autostart(self.settings["start_with_windows"], [BACKGROUND_ARG])

    # ------------------------------------------------------------------ knowledge base updates

    def check_kb_update_silently(self):
        if getattr(sys, "frozen", False) and osapi.IS_MAC:
            # no silent self-update on macOS (the installer is a Windows .exe): point at the new DMG instead
            def mac_update():
                rel = updater.newer_release(__version__)
                if rel:
                    self.main_thread.call.emit(lambda: self.announce_update(*rel))
            threading.Thread(target=mac_update, daemon=True).start()
        elif getattr(sys, "frozen", False) and not self.pending_installer and not getattr(self, "_downloading", False):
            def app_update():
                rel = updater.newer_release(__version__)
                if not rel:
                    return
                self.main_thread.call.emit(lambda: self.update_found(rel[0]))
            threading.Thread(target=app_update, daemon=True).start()

        if self.overlay.busy or getattr(self.overlay, "_syncing", False):
            return                      # the 3-hourly timer tries again later

        def work():
            before = updater.local_version()
            self.brain.shutdown()       # the warm AI process runs inside the KB folder being replaced
            if updater.update_kb():
                report.log.info("knowledge base updated to %s", updater.local_version())
                self.main_thread.call.emit(self.reload_kb)
                self.main_thread.call.emit(lambda: self.kb_updated(before))
        threading.Thread(target=work, daemon=True).start()

    def announce_update(self, version: str, url: str):
        if getattr(self, "_mac_announced", None) == version:
            return                       # the 3-hourly check found the same version again
        self._mac_announced = version
        t = I18n(self.settings["language"])
        self.toast(t("update_available", version=version), t("update_available_mac"), timeout_ms=20000)
        a = QAction(t("update_available", version=version), self._tray_menu, triggered=lambda: webbrowser.open(url))
        self._tray_menu.insertAction(self._tray_menu.actions()[2], a)   # right under the header

    def update_found(self, version: str):
        """A newer version exists: say so at once, and download it in the background (with progress)."""
        if self.pending_installer or getattr(self, "_downloading", False):
            return
        self._update_version = version
        self.overlay.show_update(version, "available")
        self._start_download()

    def _start_download(self):
        self._downloading = True
        version = getattr(self, "_update_version", "")

        def progress(done, total):
            if total and getattr(self, "_update_clicked", False):
                pct = done * 100 / total
                if pct - getattr(self, "_last_pct", -1) >= 1 or done == total:
                    self._last_pct = pct
                    self.main_thread.call.emit(lambda p=pct: self.overlay.show_update(version, "downloading", p))

        def work():
            path = updater.download_app_update(__version__, progress)
            self._downloading = False
            self.main_thread.call.emit(lambda: self.app_update_ready(path) if path else self._download_failed())
        threading.Thread(target=work, daemon=True).start()

    def _download_failed(self):
        if getattr(self, "_update_clicked", False):
            self.overlay.show_update(getattr(self, "_update_version", ""), "failed")
        self._update_clicked = False

    def app_update_ready(self, path: str):
        """A newer version is downloaded and verified: offer it at the top of the chat and in the tray."""
        self.pending_installer = path
        version = updater.installer_version(path)
        if getattr(self, "_update_clicked", False):
            self._install_now()          # the player is waiting on the progress bar: go on
            return
        t = I18n(self.settings["language"])
        self.overlay.show_update(version, "ready")
        self.toast(t("update_bar", version=version), t("update_ready"))
        self.tray.hide()
        self.make_tray()   # adds "Update to X" to the tray menu

    def update_now(self):
        """The player pressed "Update now": show the download, then install and reopen with what's new."""
        self._update_clicked = True
        if not self.overlay.isVisible():
            self.overlay.toggle(self.capture)
        if self.pending_installer:
            self._install_now()
        elif getattr(self, "_downloading", False):
            self._last_pct = -1
            self.overlay.show_update(getattr(self, "_update_version", ""), "downloading", 0)
        else:                                   # a failed download: try again
            self.overlay.show_update(getattr(self, "_update_version", ""), "downloading", 0)
            self._start_download()

    def _install_now(self):
        """Say what happens next, then close: the installer shows its progress and opens the new version."""
        version = updater.installer_version(self.pending_installer)
        self.overlay.show_update(version, "installing")
        self._reopen_after_update = True
        QTimer.singleShot(1800, self.qapp.quit)

    def update_kb_interactive(self):
        t = I18n(self.settings["language"])
        before = updater.local_version()
        if updater.update_kb():
            self.reload_kb()
            self.kb_updated(before, interactive=True)
        else:
            self.toast(t("kb_uptodate"))

    def kb_updated(self, before: str, interactive: bool = False):
        """Tell the player exactly what the update changed (patch notes), not just that it happened."""
        t = I18n(self.settings["language"])
        entries = updater.changes_since(before)
        if not entries:
            self.toast(t("kb_updated"))
            return
        if interactive:
            self.show_patch_notes(entries)
            return
        hits = wishlist.touched(entries, wishlist.items(self.settings, self.profiles.active_id), self.kb)
        if hits:
            self.overlay.add_notice(lambda t: t("wish_kb_hit", names=", ".join(hits)), lambda t: t("patch_notes_show"),
                                    lambda: self.show_patch_notes(entries))
        # in the chat, where the player looks next; a dialog over the game would interrupt play
        self.overlay.add_notice(lambda t: t("patch_notes_summary", summary=summary(t, entries)),
                                lambda t: t("patch_notes_show"),
                                lambda: self.show_patch_notes(entries))
        if not self.overlay.isVisible():
            self.toast(t("kb_updated"), t("kb_updated_open"))

    def show_tools(self, page: str = "train"):
        from .ui.tools import ToolsDialog

        def make():
            dlg = ToolsDialog(self.kb, self.profiles, self.settings, self.settings["language"], self.style(),
                              self.exp_meter, page)
            dlg.sync_requested.connect(self.overlay.sync_profile)
            dlg.ask_requested.connect(self.ask_from_tools)
            dlg.tag_requested.connect(self.ask_about_guide)
            dlg.guide_requested.connect(self.show_guides)
            return dlg
        self.open_window("tools", make)

    def ask_from_tools(self, question: str, with_screenshot: bool):
        if not self.overlay.isVisible():
            self.overlay.toggle(self.capture)
        if with_screenshot:
            self.overlay.ask_with_screenshot(question)
        else:
            self.overlay.ask(question)

    def _tools_call(self, method: str, *args):
        tools = self.__dict__.get("_windows", {}).get("tools")
        if tools is not None:
            getattr(tools, method)(*args)

    def on_profile_changed(self):
        self._tools_call("profile_changed")

    def show_guides(self, open_key: str | None = None):
        from .ui.guides import GuidesDialog
        def make():
            dlg = GuidesDialog(self.kb, self.profiles.active, self.settings["language"], self.style())
            dlg.ask_requested.connect(self.ask_about_guide)
            return dlg
        dlg = self.open_window("guides", make)
        if open_key and self.kb.get(open_key):
            dlg.open_guide(open_key)

    def ask_about_guide(self, key: str):
        """Tag the guide in the chat, so the next question is about it (Claude reads the page)."""
        if not self.overlay.isVisible():
            self.overlay.toggle(self.capture)
        self.overlay.set_tags([key])
        self.overlay.input.setFocus()

    def show_history(self):
        from . import pins
        from .ui.pinsview import HistoryDialog
        c = self.profiles.active
        if not c:
            return
        pairs = pins.conversations(History(c.id).recent(100000))
        def make():
            dlg = HistoryDialog(pairs, c.name, self.settings["language"], self.style())
            dlg.pin_requested.connect(lambda q, a, cid=c.id: self.overlay.pin_answer(q, a, cid))
            return dlg
        self.open_window(f"history:{c.id}", make)

    def show_wishlist(self):
        from .ui.wishlist import WishlistDialog
        keys = wishlist.items(self.settings, self.profiles.active_id)
        self.open_window(f"wishlist:{self.profiles.active_id}",
                         lambda: WishlistDialog(keys, self.kb, self.settings["language"], self.style()))

    def show_patch_notes(self, entries: list[dict] | None = None):
        if entries is None:
            entries = updater.changelog()[:5]
        self.open_window("patch_notes", lambda: PatchNotesDialog(entries, self.settings["language"], self.style(),
                                                                 self.kb))

    def reload_kb(self):
        self.kb = KnowledgeBase()
        self.brain.kb = self.kb
        self.overlay.kb = self.kb

    def shutdown(self):
        telemetry.flush()
        try:
            self.overlay.save_session_summary()   # quitting ends the session: show it next time
        except Exception:
            pass
        try:
            self.brain.shutdown()
        except Exception:
            pass
        try:
            self.hotkeys.close()
        except Exception:
            pass
        if getattr(self, "pending_installer", None):
            updater.run_installer_silently(self.pending_installer, reopen=getattr(self, "_reopen_after_update", False),
                                           lang=self.settings["language"] or "he")



_RUNNING = None


def _hold_running_mutex():
    """Windows: wait while an update installs, then hold a named mutex the installer waits on.
    (The launchers already waited before importing anything heavy; this covers other entry points.)"""
    global _RUNNING
    if sys.platform != "win32":
        return
    import ctypes

    from .setupwait import wait_for_setup
    wait_for_setup()
    k32 = ctypes.windll.kernel32
    _RUNNING = k32.CreateMutexW(None, False, "MapleHelperRunning")


def main():
    if any(a.startswith("--selftest") for a in sys.argv[1:]):
        from . import selftest   # `Maple Helper.exe --selftest <report file>`, see selftest.py
        return selftest.main(sys.argv[1:])
    osapi.prepare_process()
    report.setup_logging()
    report.log.info("Maple Helper %s starting on %s (%s)", __version__, sys.platform, " ".join(sys.argv[1:]) or "no args")
    qapp = QApplication(sys.argv)
    qapp.setStyle("Fusion")   # the native Windows 11 style ignores rounded corners on buttons
    qapp.setApplicationName(APP_NAME)
    qapp.setApplicationDisplayName(APP_NAME)
    lock = QLockFile(str(DATA_DIR / "app.lock"))
    if not lock.tryLock(100):
        return 0  # already running
    _hold_running_mutex()
    app = MapleHelperApp(qapp)
    if not app.start():
        return 0
    return qapp.exec()


if __name__ == "__main__":
    sys.exit(main())
