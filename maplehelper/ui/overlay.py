"""The in-game chat window: transparent, always on top, draggable across monitors, F9 only to close."""
from __future__ import annotations

import time

from PySide6.QtCore import QObject, QPoint, QRect, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QIcon, QPixmap
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QSizeGrip,
                               QToolButton, QVBoxLayout, QWidget)

from .. import bidi, winapi
from ..brain import Answer, Brain
from ..i18n import I18n
from ..kb import KnowledgeBase
from ..store import ASSETS, History, Profiles, Settings
from .widgets import Bubble, BubbleRow, EntityCard, QuickButton, SystemLine

SLOW_AFTER_MS = 30_000


class AskWorker(QObject):
    delta = Signal(str)
    done = Signal(object)

    def __init__(self, brain: Brain, question: str, character, history, shot: bytes | None):
        super().__init__()
        self.brain, self.question, self.character, self.history, self.shot = brain, question, character, history, shot

    def run(self):
        ans = self.brain.ask(self.question, self.character, self.history, self.shot, on_delta=self.delta.emit)
        self.done.emit(ans)


class TitleBar(QWidget):
    """Drag handle for the frameless window."""

    def __init__(self, window: QWidget):
        super().__init__()
        self.setObjectName("TitleBar")
        self._win = window
        self._drag: QPoint | None = None

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = e.globalPosition().toPoint() - self._win.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag is not None and e.buttons() & Qt.LeftButton:
            self._win.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, e):
        if self._drag is not None:
            self._drag = None
            self._win.save_geometry()


class Overlay(QWidget):
    settings_requested = Signal()
    profile_requested = Signal()

    def __init__(self, settings: Settings, profiles: Profiles, kb: KnowledgeBase, brain: Brain):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle("Maple Helper")
        self.settings, self.profiles, self.kb, self.brain = settings, profiles, kb, brain
        self.t = I18n(settings["language"] or "he")
        self.game_hwnd: int | None = None
        self.shot: bytes | None = None          # screenshot for the next question
        self.shot_used = False
        self.busy = False
        self._thread: QThread | None = None
        self._pending_bubble: Bubble | None = None
        self._slow_timer = QTimer(self, singleShot=True, interval=SLOW_AFTER_MS, timeout=self._on_slow)
        self._session_started: float | None = None
        self._build()
        self.apply_language()
        self.restore_geometry()

    # ------------------------------------------------------------------ layout

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.panel = QFrame(objectName="Panel")
        outer.addWidget(self.panel)
        lay = QVBoxLayout(self.panel)
        lay.setContentsMargins(12, 8, 12, 10)
        lay.setSpacing(8)

        # title bar: logo · name · profile chip · settings
        self.title_bar = TitleBar(self)
        tb = QHBoxLayout(self.title_bar)
        tb.setContentsMargins(0, 0, 0, 0)
        logo = QLabel()
        icon = ASSETS / "brand" / "icon-64.png"
        if icon.exists():
            logo.setPixmap(QPixmap(str(icon)).scaled(24, 24, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        tb.addWidget(logo)
        self.title = QLabel("Maple Helper", objectName="Title")
        tb.addWidget(self.title)
        tb.addStretch(1)
        self.profile_chip = QPushButton(objectName="ProfileChip")
        self.profile_chip.setCursor(Qt.PointingHandCursor)
        self.profile_chip.clicked.connect(self.profile_requested.emit)
        tb.addWidget(self.profile_chip)
        self.settings_btn = QToolButton(objectName="IconBtn", text="⚙")
        self.settings_btn.setCursor(Qt.PointingHandCursor)
        self.settings_btn.clicked.connect(self.settings_requested.emit)
        tb.addWidget(self.settings_btn)
        lay.addWidget(self.title_bar)

        # messages
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.feed = QWidget()
        self.feed_lay = QVBoxLayout(self.feed)
        self.feed_lay.setContentsMargins(0, 0, 4, 0)
        self.feed_lay.setSpacing(8)
        self.feed_lay.addStretch(1)
        self.scroll.setWidget(self.feed)
        lay.addWidget(self.scroll, 1)
        self.scroll.verticalScrollBar().rangeChanged.connect(
            lambda _a, b: self.scroll.verticalScrollBar().setValue(b))

        # quick buttons
        self.quick = QHBoxLayout()
        self.quick.setSpacing(6)
        self.quick_buttons = {}
        for key in ("grind", "item", "quest", "skill"):
            b = QuickButton("")
            b.clicked.connect(lambda _=False, k=key: self.ask(self.t(f"qb_{k}_q")))
            self.quick_buttons[key] = b
            self.quick.addWidget(b)
        self.quick.addStretch(1)
        lay.addLayout(self.quick)

        # input row
        row = QHBoxLayout()
        row.setSpacing(6)
        self.input = QLineEdit(objectName="Input")
        self.input.returnPressed.connect(self._send_typed)
        self.input.textChanged.connect(self._auto_direction)
        row.addWidget(self.input, 1)
        self.recapture_btn = QToolButton(objectName="IconBtn", text="📷")
        self.recapture_btn.setCursor(Qt.PointingHandCursor)
        self.recapture_btn.clicked.connect(self.recapture)
        row.addWidget(self.recapture_btn)
        self.mic_dot = QLabel(objectName="MicDot")
        self.mic_dot.setFixedSize(10, 10)
        self.mic_dot.hide()
        row.addWidget(self.mic_dot)
        lay.addLayout(row)

        grip_row = QHBoxLayout()
        grip_row.setContentsMargins(0, 0, 0, 0)
        grip_row.addStretch(1)
        self.grip = QSizeGrip(self)
        self.grip.setFixedSize(14, 14)
        grip_row.addWidget(self.grip)
        lay.addLayout(grip_row)

    def apply_language(self):
        self.t = I18n(self.settings["language"] or "he")
        self.setLayoutDirection(Qt.RightToLeft if self.t.rtl else Qt.LeftToRight)
        self.input.setPlaceholderText(self.t("input_placeholder"))
        self.recapture_btn.setToolTip(self.t("recapture"))
        self.settings_btn.setToolTip(self.t("settings"))
        for key, b in self.quick_buttons.items():
            b.setText(self.t(f"qb_{key}"))
        self.refresh_profile_chip()

    def refresh_profile_chip(self):
        c = self.profiles.active
        if not c:
            self.profile_chip.hide()
            return
        self.profile_chip.show()
        # name · Lv 35 · Fighter: English parts isolated for RTL
        self.profile_chip.setText(bidi.plain(f"{c.name} · {self.t('level')} {c.level} · {c.job}", self.t.rtl))

    def _auto_direction(self, text: str):
        """The input box follows what is being typed (first strong character)."""
        d = bidi.direction(text) if text.strip() else ("rtl" if self.t.rtl else "ltr")
        self.input.setLayoutDirection(Qt.RightToLeft if d == "rtl" else Qt.LeftToRight)
        self.input.setAlignment(Qt.AlignRight if d == "rtl" else Qt.AlignLeft)

    # ------------------------------------------------------------------ geometry

    def restore_geometry(self):
        g = self.settings["window"]
        screens = QGuiApplication.screens()
        if g:
            rect = QRect(g["x"], g["y"], g["w"], g["h"])
            if any(s.availableGeometry().intersects(rect) for s in screens):
                self.setGeometry(rect)
                return
        self.place_default()

    def place_default(self, near_hwnd: int | None = None):
        """Top-right corner of the game's screen (or the primary screen)."""
        screen = QGuiApplication.primaryScreen()
        rect = winapi.window_rect(near_hwnd) if near_hwnd else None
        if rect:
            s = QGuiApplication.screenAt(QPoint(rect[0] + rect[2] // 2, rect[1] + rect[3] // 2))
            screen = s or screen
        a = screen.availableGeometry()
        w, h = 420, min(620, a.height() - 80)
        self.setGeometry(a.right() - w - 24, a.top() + 60, w, h)

    def save_geometry(self):
        g = self.geometry()
        self.settings["window"] = {"x": g.x(), "y": g.y(), "w": g.width(), "h": g.height()}

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.isVisible():
            QTimer.singleShot(300, self.save_geometry)

    # ------------------------------------------------------------------ show / hide

    def open_overlay(self, shot: bytes | None, game_hwnd: int | None):
        self.shot, self.shot_used, self.game_hwnd = shot, False, game_hwnd
        if not self.settings["window"]:
            self.place_default(game_hwnd)
        if self._session_started is None:
            self._session_started = time.time()
        self.show()
        self.raise_()
        self.activateWindow()
        winapi.focus_window(int(self.winId()))
        self.input.setFocus()

    def close_overlay(self):
        self.hide()
        if self.game_hwnd:
            winapi.focus_window(self.game_hwnd)

    def toggle(self, shot_provider):
        if self.isVisible():
            self.close_overlay()
        else:
            hwnd = winapi.find_game_window()
            self.open_overlay(shot_provider(hwnd), hwnd)

    def keyPressEvent(self, e):
        # Esc deliberately does nothing: only F9 closes (spec).
        if e.key() == Qt.Key_Escape:
            return
        super().keyPressEvent(e)

    def recapture(self):
        was = self.isVisible()
        self.hide()
        QTimer.singleShot(150, lambda: self._do_recapture(was))

    def _do_recapture(self, was_visible: bool):
        hwnd = self.game_hwnd or winapi.find_game_window()
        self.shot = winapi.capture_game(hwnd)
        self.shot_used = False
        if was_visible:
            self.show()
            self.activateWindow()
            self.input.setFocus()
        self.add_system("📷 ✓")

    # ------------------------------------------------------------------ feed

    def _add_widget(self, w: QWidget):
        self.feed_lay.insertWidget(self.feed_lay.count() - 1, w)

    def add_bubble(self, text: str, role: str) -> Bubble:
        b = Bubble(text, role, self.t.rtl)
        self._add_widget(BubbleRow(b, self.t.rtl))
        return b

    def add_system(self, text: str):
        self._add_widget(SystemLine(text))

    def add_cards(self, keys: list[str]):
        for k in keys:
            self._add_widget(EntityCard(self.kb, k, self.t.lang))

    def add_confirm(self, text: str, on_yes):
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(SystemLine(text), 1)
        yes = QPushButton(self.t("yes"), objectName="Quick")
        no = QPushButton(self.t("no"), objectName="Quick")
        yes.clicked.connect(lambda: (on_yes(), row.setDisabled(True)))
        no.clicked.connect(lambda: row.setDisabled(True))
        lay.addWidget(yes)
        lay.addWidget(no)
        self._add_widget(row)

    # ------------------------------------------------------------------ asking

    def _send_typed(self):
        q = self.input.text().strip()
        if q:
            self.input.clear()
            self.ask(q)

    def ask(self, question: str):
        if self.busy or not question.strip():
            return
        c = self.profiles.active
        history = History(c.id) if c else None
        self.add_bubble(question, "user")
        shot = None if self.shot_used else self.shot
        if shot is None and not self.shot_used and not self.game_hwnd:
            self.add_system(self.t("no_game"))
        self.shot_used = True
        if history:
            history.append("user", question)
        self._pending_bubble = self.add_bubble(self.t("thinking"), "assistant")
        self.busy = True
        self._slow_timer.start()

        self._thread = QThread(self)
        self._worker = AskWorker(self.brain, question, c, history, shot)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.delta.connect(self._on_delta)
        self._worker.done.connect(lambda ans: self._on_done(ans, history))
        self._worker.done.connect(self._thread.quit)
        self._thread.start()

    def _on_delta(self, text: str):
        if self._pending_bubble and text:
            self._pending_bubble.set_text(text)

    def _on_slow(self):
        if self.busy:
            self.add_confirm(self.t("slow"), self.brain.cancel)

    def _on_done(self, ans: Answer, history: History | None):
        self._slow_timer.stop()
        self.busy = False
        if ans.error:
            key = f"err_{ans.error}" if ans.error in ("offline", "not_logged_in", "usage_limit",
                                                      "claude_not_installed") else "err_generic"
            self._pending_bubble.set_text(self.t(key))
            return
        self._pending_bubble.set_text(ans.text)
        if history:
            history.append("assistant", ans.text, ans.entities)
        if ans.entities:
            self.add_cards(ans.entities)
        self._apply_profile_update(ans.profile_update)

    def _apply_profile_update(self, update: dict):
        c = self.profiles.active
        if not c or not update:
            return
        new_level = update.get("level")
        if isinstance(new_level, int) and new_level < c.level:
            # a lower level usually means the screenshot showed another character: ask first
            rest = {k: v for k, v in update.items() if k != "level"}
            self._show_changes(self.profiles.apply_update(rest))
            self.add_confirm(self.t("confirm_profile", level=new_level),
                             lambda: self._show_changes(self.profiles.apply_update({"level": new_level})))
            return
        self._show_changes(self.profiles.apply_update(update))

    def _show_changes(self, changes):
        labels = {"level": "level", "job": "job", "base_class": "job", "map": "map",
                  "quest+": "quest_started", "quest-": "quest_done", "note": "note"}
        for field, value in changes:
            self.add_system(self.t("profile_updated", what=f"{self.t(labels[field])} {value}"))
        if changes:
            self.refresh_profile_chip()

    # ------------------------------------------------------------------ voice

    def voice_state(self, state: str):
        """listening | transcribing | idle | loading"""
        self.mic_dot.setVisible(state == "listening")
        if state == "listening":
            self.input.setPlaceholderText(self.t("listening"))
        elif state == "transcribing":
            self.input.setPlaceholderText(self.t("transcribing"))
        elif state == "loading":
            self.input.setPlaceholderText(self.t("voice_loading"))
        else:
            self.input.setPlaceholderText(self.t("input_placeholder"))

    def voice_text(self, text: str, send: bool):
        text = text.strip()
        if not text:
            return
        if send:
            self.ask(text)
        else:
            self.input.setText(text)
            self.input.setFocus()

    def end_session(self) -> str:
        """Transcript of this session (for the long-term summary)."""
        c = self.profiles.active
        if not c or self._session_started is None:
            return ""
        recent = [r for r in History(c.id).recent(60) if r["t"] >= self._session_started]
        self._session_started = None
        return "\n".join(f"{r['role']}: {r['text']}" for r in recent)
