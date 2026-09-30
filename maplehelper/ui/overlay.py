"""The in-game chat window: a liquid-glass panel over the game, draggable across monitors, F9 only to close."""
from __future__ import annotations

import time

from PySide6.QtCore import (QEasingCurve, QObject, QParallelAnimationGroup, QPoint, QPropertyAnimation, QRect, QRectF,
                            Qt, QThread, QTimer, Signal)
from PySide6.QtGui import QColor, QGuiApplication, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QScrollArea, QSizeGrip, QToolButton, QVBoxLayout, QWidget)

from .. import bidi, winapi
from ..brain import Answer, Brain
from ..i18n import I18n
from ..kb import KnowledgeBase
from ..store import ASSETS, History, Profiles, Settings
from . import theme
from .glass import GlassBackdrop
from .widgets import Bubble, BubbleRow, EntityCard, SystemLine

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
    """Drag handle: follows the pointer 1:1 from where it was grabbed."""

    def __init__(self, window: QWidget):
        super().__init__()
        self._win = window
        self._grab: QPoint | None = None

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._grab = e.globalPosition().toPoint() - self._win.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._grab is not None and e.buttons() & Qt.LeftButton:
            self._win.move(e.globalPosition().toPoint() - self._grab)

    def mouseReleaseEvent(self, e):
        if self._grab is not None:
            self._grab = None
            self._win.save_geometry()


class Capsule(QFrame):
    """Input capsule; highlights its border while the field has focus."""

    def set_focus_look(self, on: bool):
        self.setProperty("focus", "true" if on else "false")
        self.style().unpolish(self)
        self.style().polish(self)


class FocusLineEdit(QLineEdit):
    focus_changed = Signal(bool)

    def focusInEvent(self, e):
        super().focusInEvent(e)
        self.focus_changed.emit(True)

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        self.focus_changed.emit(False)


class Overlay(QWidget):
    settings_requested = Signal()
    profile_requested = Signal()

    def __init__(self, settings: Settings, profiles: Profiles, kb: KnowledgeBase, brain: Brain):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setObjectName("Overlay")
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
        self._anim: QParallelAnimationGroup | None = None
        self.backdrop = GlassBackdrop(self)
        self._build()
        self.apply_language()
        self.restore_geometry()

    # ------------------------------------------------------------------ material

    SHADOW = 12   # room around the panel for its soft shadow

    def showEvent(self, e):
        super().showEvent(e)
        self.apply_capture_mode()

    def apply_capture_mode(self):
        """Hidden from captures → live frosted backdrop of the game.
        Visible in captures (screenshots, streams) → the backdrop can't sample behind itself,
        so the glass becomes a uniform frosted tint."""
        visible = bool(self.settings["show_in_captures"])
        winapi.set_capture_visibility(int(self.winId()), visible)
        if visible:
            self.backdrop.stop()
            self.backdrop.pixmap = None
        elif self.isVisible():
            self.backdrop.start()
        self.update()

    def hideEvent(self, e):
        super().hideEvent(e)
        self.backdrop.stop()

    def _panel_path(self) -> QPainterPath:
        m = self.SHADOW
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()).adjusted(m + 0.5, m + 0.5, -m - 0.5, -m - 0.5),
                            theme.RADIUS, theme.RADIUS)
        return path

    def paintEvent(self, e):
        """Liquid glass: the blurred game behind, a neutral tint, a light-catching sheen and rim."""
        c = theme.P()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        m = self.SHADOW
        # soft shadow: stacked rounded rects fading out
        for i in range(m, 0, -2):
            sh = QPainterPath()
            sh.addRoundedRect(QRectF(self.rect()).adjusted(m - i, m - i + 3, -(m - i), -(m - i) + 3),
                              theme.RADIUS + i, theme.RADIUS + i)
            p.fillPath(sh, QColor(0, 0, 0, int(26 * (1 - i / m)) + 2))
        path = self._panel_path()
        p.save()
        p.setClipPath(path)
        if self.backdrop.pixmap is not None:
            p.drawPixmap(self.rect(), self.backdrop.pixmap)
            alpha = c["glass_alpha"]
        else:
            alpha = c["solid_alpha"]
        tint = QColor(*c["glass"])
        tint.setAlphaF(alpha)
        p.fillPath(path, tint)
        sheen = QLinearGradient(0, m, 0, m + min(170, self.height()))
        sheen.setColorAt(0.0, QColor(255, 255, 255, c["sheen"]))
        sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.fillPath(path, sheen)
        p.restore()
        rim = QLinearGradient(0, m, 0, self.height() - m)
        rim.setColorAt(0.0, QColor(255, 255, 255, c["rim_top"]))
        rim.setColorAt(0.4, QColor(255, 255, 255, c["rim"]))
        rim.setColorAt(1.0, QColor(255, 255, 255, c["rim"] // 2))
        p.setPen(QPen(rim, 1))
        p.drawPath(path)

    # ------------------------------------------------------------------ layout

    def _icon_button(self, glyph: str, tip: str = "") -> QToolButton:
        b = QToolButton(objectName="Icon", text=glyph)
        b.setCursor(Qt.PointingHandCursor)
        b.setToolTip(tip)
        return b

    def _build(self):
        lay = QVBoxLayout(self)
        m = self.SHADOW
        lay.setContentsMargins(m + 14, m + 10, m + 14, m + 12)
        lay.setSpacing(10)

        # header: app mark · name · profile pill · settings
        self.title_bar = TitleBar(self)
        tb = QHBoxLayout(self.title_bar)
        tb.setContentsMargins(2, 2, 0, 0)
        tb.setSpacing(8)
        logo = QLabel()
        icon = ASSETS / "brand" / "icon-64.png"
        if icon.exists():
            logo.setPixmap(QPixmap(str(icon)).scaled(22, 22, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        tb.addWidget(logo)
        self.title = QLabel("Maple Helper", objectName="Title")
        tb.addWidget(self.title)
        tb.addStretch(1)
        self.profile_chip = QPushButton(objectName="ProfilePill")
        self.profile_chip.setCursor(Qt.PointingHandCursor)
        self.profile_chip.clicked.connect(self.profile_requested.emit)
        tb.addWidget(self.profile_chip)
        self.settings_btn = self._icon_button(theme.ICON["settings"])
        self.settings_btn.clicked.connect(self.settings_requested.emit)
        tb.addWidget(self.settings_btn)
        lay.addWidget(self.title_bar)

        # conversation
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.feed = QWidget(objectName="Feed")
        self.feed_lay = QVBoxLayout(self.feed)
        self.feed_lay.setContentsMargins(0, 4, 6, 4)
        self.feed_lay.setSpacing(8)
        self.feed_lay.addStretch(1)
        self.scroll.setWidget(self.feed)
        lay.addWidget(self.scroll, 1)
        self.scroll.verticalScrollBar().rangeChanged.connect(
            lambda _a, b: self.scroll.verticalScrollBar().setValue(b))

        # input capsule: [camera] field [mic] (send)
        self.capsule = Capsule(objectName="Capsule")
        self.capsule.setFixedHeight(42)
        row = QHBoxLayout(self.capsule)
        row.setContentsMargins(6, 5, 6, 5)
        row.setSpacing(2)
        self.recapture_btn = self._icon_button(theme.ICON["camera"])
        self.recapture_btn.clicked.connect(self.recapture)
        row.addWidget(self.recapture_btn)
        self.input = FocusLineEdit(objectName="Input")
        self.input.returnPressed.connect(self._send_typed)
        self.input.textChanged.connect(self._on_text)
        self.input.focus_changed.connect(self.capsule.set_focus_look)
        row.addWidget(self.input, 1)
        self.mic_btn = self._icon_button(theme.ICON["mic"])
        self.mic_btn.setEnabled(False)   # push-to-talk key; the icon shows the state
        row.addWidget(self.mic_btn)
        self.send_btn = QToolButton(objectName="Send", text=theme.ICON["send"])
        self.send_btn.setCursor(Qt.PointingHandCursor)
        self.send_btn.clicked.connect(self._send_typed)
        self.send_btn.setEnabled(False)
        row.addWidget(self.send_btn)
        lay.addWidget(self.capsule)

        self.grip = QSizeGrip(self)
        self.grip.setFixedSize(16, 16)
        self.grip.setStyleSheet("background: transparent;")

    def resizeEvent(self, e):
        super().resizeEvent(e)
        m = self.SHADOW
        self.grip.move(self.width() - m - 18 if not self.t.rtl else m + 2, self.height() - m - 18)
        if self.isVisible():
            self.backdrop.refresh()
            QTimer.singleShot(300, self.save_geometry)

    def apply_language(self):
        self.t = I18n(self.settings["language"] or "he")
        self.setLayoutDirection(Qt.RightToLeft if self.t.rtl else Qt.LeftToRight)
        hk_toggle, hk_voice = self.settings["hotkey_toggle"], self.settings["hotkey_voice"]
        self._placeholder = self.t("input_placeholder").replace("F10", hk_voice)
        self.input.setPlaceholderText(bidi.plain(self._placeholder, self.t.rtl))
        self.recapture_btn.setToolTip(self.t("recapture"))
        self.settings_btn.setToolTip(self.t("settings"))
        self.mic_btn.setToolTip(self.t("hotkey_voice") + f" ({hk_voice})")
        self._on_text(self.input.text())
        self.refresh_profile_chip()

    def refresh_profile_chip(self):
        c = self.profiles.active
        if not c:
            self.profile_chip.hide()
            return
        self.profile_chip.show()
        self.profile_chip.setText(bidi.plain(f"{c.name} · {self.t('level')} {c.level} · {c.job}", self.t.rtl))

    def _on_text(self, text: str):
        """The field follows what is being typed; send lights up only when there is something to send."""
        d = bidi.direction(text) if text.strip() else ("rtl" if self.t.rtl else "ltr")
        self.input.setLayoutDirection(Qt.RightToLeft if d == "rtl" else Qt.LeftToRight)
        self.input.setAlignment(Qt.AlignRight if d == "rtl" else Qt.AlignLeft)
        self.send_btn.setEnabled(bool(text.strip()) and not self.busy)

    # ------------------------------------------------------------------ geometry

    def restore_geometry(self):
        g = self.settings["window"]
        if g:
            rect = QRect(g["x"], g["y"], g["w"], g["h"])
            if any(s.availableGeometry().intersects(rect) for s in QGuiApplication.screens()):
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
        w, h = 420, min(640, a.height() - 80)
        self.setGeometry(a.right() - w - 24, a.top() + 60, w, h)

    def save_geometry(self):
        g = self.geometry()
        self.settings["window"] = {"x": g.x(), "y": g.y(), "w": g.width(), "h": g.height()}

    # ------------------------------------------------------------------ show / hide

    def _materialize(self, show: bool, on_done=None):
        """The material arrives: opacity and a small scale settle together (critically damped, no bounce)."""
        if self._anim:
            self._anim.stop()           # interruptible: start from wherever it is now
        g = self.geometry()
        small = QRect(g.x() + round(g.width() * 0.015), g.y() + round(g.height() * 0.015),
                      round(g.width() * 0.97), round(g.height() * 0.97))
        fade = QPropertyAnimation(self, b"windowOpacity")
        fade.setDuration(220 if show else 150)
        fade.setStartValue(self.windowOpacity())
        fade.setEndValue(1.0 if show else 0.0)
        fade.setEasingCurve(QEasingCurve.OutCubic)
        grp = QParallelAnimationGroup(self)
        grp.addAnimation(fade)
        if show:
            self._target_geometry = g
            self.setGeometry(small)
            grow = QPropertyAnimation(self, b"geometry")
            grow.setDuration(240)
            grow.setStartValue(small)
            grow.setEndValue(g)
            grow.setEasingCurve(QEasingCurve.OutCubic)
            grp.addAnimation(grow)
        if on_done:
            grp.finished.connect(on_done)
        self._anim = grp
        grp.start()

    def open_overlay(self, shot: bytes | None, game_hwnd: int | None):
        self.shot, self.shot_used, self.game_hwnd = shot, False, game_hwnd
        if not self.settings["window"]:
            self.place_default(game_hwnd)
        if self._session_started is None:
            self._session_started = time.time()
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()
        self.activateWindow()
        winapi.focus_window(int(self.winId()))
        self.input.setFocus()
        self._materialize(True)

    def close_overlay(self):
        def done():
            self.hide()
            self.setWindowOpacity(1.0)
        self._materialize(False, done)
        if self.game_hwnd:
            winapi.focus_window(self.game_hwnd)

    def toggle(self, shot_provider):
        if self.isVisible() and self.windowOpacity() > 0.5:
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
        if self.settings["show_in_captures"]:
            # the chat would appear in the shot: step aside for a moment
            self.setWindowOpacity(0.0)
            QTimer.singleShot(120, self._do_recapture)
        else:
            # hidden from capture: the game can be captured with the chat open
            self._do_recapture()

    def _do_recapture(self):
        hwnd = self.game_hwnd or winapi.find_game_window()
        self.shot = winapi.capture_game(hwnd)
        self.shot_used = False
        self.setWindowOpacity(1.0)
        self.add_system("✓ " + self.t("recapture"))

    # ------------------------------------------------------------------ feed

    def _add_widget(self, w: QWidget):
        self.feed_lay.insertWidget(self.feed_lay.count() - 1, w)
        # new content fades in rather than popping
        eff = QGraphicsOpacityEffect(w)
        w.setGraphicsEffect(eff)
        a = QPropertyAnimation(eff, b"opacity", w)
        a.setDuration(180)
        a.setStartValue(0.0)
        a.setEndValue(1.0)
        a.setEasingCurve(QEasingCurve.OutCubic)
        a.finished.connect(lambda: w.setGraphicsEffect(None))
        a.start()

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
        yes = QPushButton(self.t("yes"), objectName="Chip")
        no = QPushButton(self.t("no"), objectName="Chip")
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
        self.send_btn.setEnabled(False)
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
        self._on_text(self.input.text())
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
        self.mic_btn.setProperty("active", "true" if state == "listening" else "false")
        self.mic_btn.style().unpolish(self.mic_btn)
        self.mic_btn.style().polish(self.mic_btn)
        text = {"listening": self.t("listening"), "transcribing": self.t("transcribing"),
                "loading": self.t("voice_loading")}.get(state, self._placeholder)
        self.input.setPlaceholderText(bidi.plain(text, self.t.rtl))

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
