"""The in-game chat window: a liquid-glass panel over the game, draggable across monitors, F9 only to close."""
from __future__ import annotations

import time

from PySide6.QtCore import (QEasingCurve, QObject, QParallelAnimationGroup, QPoint, QPropertyAnimation, QRect, QRectF,
                            Qt, QThread, QTimer, Signal)
from PySide6.QtGui import QGuiApplication, QPainterPath, QPixmap
from PySide6.QtWidgets import (QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QScrollArea, QSizeGrip, QToolButton, QVBoxLayout, QWidget)

from .. import bidi, winapi
from ..brain import Answer, Brain
from ..i18n import I18n
from ..kb import KnowledgeBase
from ..store import ASSETS, History, Profiles, Settings
from . import theme
from .glass import paint_glass
from .minibubble import MiniBubble
from .widgets import Bubble, BubbleRow, EntityCard, ProfileCard, SystemLine, TileGrid



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
    mic_clicked = Signal()

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
        self._session_started: float | None = None
        self._anim: QParallelAnimationGroup | None = None
        self.bubble = MiniBubble()
        self.bubble.clicked.connect(self.restore_from_bubble)
        self.bubble.moved.connect(lambda pt: self.settings.__setitem__("bubble_pos", {"x": pt.x(), "y": pt.y()}))
        self.shot_provider = None
        self._build()
        self.apply_language()
        self.restore_geometry()

    # ------------------------------------------------------------------ material

    SHADOW = 12   # room around the panel for its soft shadow

    def apply_capture_mode(self):
        """Opaque window, visible in screenshots and recordings like any app."""
        self.update()

    def _panel_path(self) -> QPainterPath:
        m = self.SHADOW
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()).adjusted(m + 0.5, m + 0.5, -m - 0.5, -m - 0.5),
                            theme.RADIUS, theme.RADIUS)
        return path

    def paintEvent(self, e):
        """Liquid glass: the blurred game behind, a neutral tint, a light-catching sheen and rim."""
        paint_glass(self, None)

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
        self.settings_btn = self._icon_button(theme.ICON["settings"])
        self.settings_btn.clicked.connect(self.settings_requested.emit)
        tb.addWidget(self.settings_btn)
        # window controls sit at the header's edge (left in Hebrew, right in English)
        self.min_btn = self._icon_button(theme.ICON["minimize"])
        self.min_btn.clicked.connect(self.minimize)
        tb.addWidget(self.min_btn)
        self.close_btn = self._icon_button(theme.ICON["close"])
        self.close_btn.setObjectName("IconClose")
        self.close_btn.clicked.connect(self.close_overlay)
        tb.addWidget(self.close_btn)
        lay.addWidget(self.title_bar)

        # the character, pinned at the top of the conversation
        self.profile_card = ProfileCard()
        self.profile_card.refresh_requested.connect(self.sync_profile)
        lay.addWidget(self.profile_card)

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
        self.mic_btn.clicked.connect(self.mic_clicked.emit)   # click to talk; holding the voice key works too
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
            QTimer.singleShot(300, self.save_geometry)

    def apply_language(self):
        self.t = I18n(self.settings["language"] or "he")
        self.setLayoutDirection(Qt.RightToLeft if self.t.rtl else Qt.LeftToRight)
        hk_voice = self.settings["hotkey_voice"]
        self._placeholder = self.t("input_placeholder").replace("F10", hk_voice)
        self.input.setPlaceholderText(bidi.plain(self._placeholder, self.t.rtl))
        self.recapture_btn.setToolTip(self.t("recapture"))
        self.settings_btn.setToolTip(self.t("settings"))
        self.profile_card.refresh.setToolTip(self.t("refresh_tip"))
        self.min_btn.setToolTip(self.t("minimize"))
        self.close_btn.setToolTip(self.t("close_chat").replace("F9", self.settings["hotkey_toggle"]))
        self.mic_btn.setToolTip(self.t("mic_tip", key=hk_voice))
        self._on_text(self.input.text())
        self.refresh_profile_chip()

    def refresh_profile_chip(self):
        c = self.profiles.active
        self.profile_card.setVisible(c is not None)
        if c:
            self.profile_card.show_character(c, self.profiles.avatar_path(c), self.kb, self.t.rtl)

    def _on_text(self, text: str):
        """The field follows what is being typed; send lights up only when there is something to send."""
        d = bidi.direction(text) if text.strip() else ("rtl" if self.t.rtl else "ltr")
        self.input.setLayoutDirection(Qt.RightToLeft if d == "rtl" else Qt.LeftToRight)
        # absolute: in an RTL widget a plain AlignRight means "trailing" = left
        self.input.setAlignment((Qt.AlignRight if d == "rtl" else Qt.AlignLeft) | Qt.AlignAbsolute | Qt.AlignVCenter)
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
        self.bubble.hide()
        if not self.isVisible():
            return
        def done():
            self.hide()
            self.setWindowOpacity(1.0)
        self._materialize(False, done)
        if self.game_hwnd:
            winapi.focus_window(self.game_hwnd)

    def minimize(self):
        """Shrink to the bubble, which appears where the chat's header was."""
        pos = self.settings["bubble_pos"]
        if pos:
            self.bubble.move(pos["x"], pos["y"])
        else:
            g = self.geometry()
            x = g.left() + self.SHADOW if self.t.rtl else g.right() - self.bubble.width() - self.SHADOW
            self.bubble.move(x, g.top() + self.SHADOW)
        self.close_overlay()
        self.bubble.show()
        self.bubble.raise_()

    def restore_from_bubble(self):
        self.bubble.hide()
        hwnd = winapi.find_game_window()
        shot = self.shot_provider(hwnd) if self.shot_provider else None
        self.open_overlay(shot, hwnd)

    def toggle(self, shot_provider):
        self.shot_provider = shot_provider
        if self.isVisible() and self.windowOpacity() > 0.5:
            self.close_overlay()
        else:
            self.bubble.hide()
            hwnd = winapi.find_game_window()
            self.open_overlay(shot_provider(hwnd), hwnd)

    def keyPressEvent(self, e):
        # Esc deliberately does nothing: F9 or the window buttons close the chat.
        if e.key() == Qt.Key_Escape:
            return
        super().keyPressEvent(e)

    def recapture(self):
        # the chat is part of the screen: step aside for a moment so the shot shows the game
        self.setWindowOpacity(0.0)
        QTimer.singleShot(120, self._do_recapture)

    def _do_recapture(self):
        hwnd = self.game_hwnd or winapi.find_game_window()
        self.shot = winapi.capture_game(hwnd)
        self.shot_used = False
        self.setWindowOpacity(1.0)
        self.add_system("✓ " + self.t("recaptured"))

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

    def clear_feed(self):
        while self.feed_lay.count() > 1:
            w = self.feed_lay.takeAt(0).widget()
            if w:
                w.deleteLater()

    def add_bubble(self, text: str, role: str) -> Bubble:
        b = Bubble(text, role, self.t.rtl)
        self._add_widget(BubbleRow(b, self.t.rtl))
        return b

    def add_system(self, text: str):
        self._add_widget(SystemLine(text))

    def add_cards(self, keys: list[str]):
        if len(keys) <= 2:
            for k in keys:
                self._add_widget(EntityCard(self.kb, k, self.t.lang))
            return
        # the subject (monster, NPC, map, quest) stays a full card; the list (drops, rewards) becomes tiles
        heads = [k for k in keys if k.split("/")[0] in ("monster", "npc", "map", "quest")][:1]
        rest = [k for k in keys if k not in heads]
        for k in heads:
            self._add_widget(EntityCard(self.kb, k, self.t.lang))
        if rest:
            self._add_widget(TileGrid(self.kb, rest))

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
        self._question_shot = shot
        if shot is None and not self.shot_used and not self.game_hwnd:
            self.add_system(self.t("no_game"))
        self.shot_used = True
        if history:
            history.append("user", question)
        self._pending_bubble = self.add_bubble(self.t("thinking"), "assistant")
        self.busy = True
        self.send_btn.setEnabled(False)

        self._thread = QThread(self)
        self._worker = AskWorker(self.brain, question, c, history, shot)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.delta.connect(self._on_delta)
        # a bound method of this QObject → Qt queues the call onto the GUI thread.
        # (a lambda here would run in the worker thread and build widgets there: crash + stray window)
        self._pending_history = history
        self._worker.done.connect(self._on_done_main)
        self._worker.done.connect(self._thread.quit)
        self._thread.start()

    def _on_delta(self, text: str):
        if self._pending_bubble and text:
            self._pending_bubble.set_text(text)

    def sync_profile(self):
        if self.busy or getattr(self, "_syncing", False):
            return
        self._syncing = True
        self.profile_card.set_busy(True, self.t("syncing"))
        # the chat is opaque and on screen: step aside for the capture
        self.setWindowOpacity(0.0)
        QTimer.singleShot(120, self._sync_capture)

    def _sync_capture(self):
        hwnd = self.game_hwnd or winapi.find_game_window()
        shot = winapi.capture_game(hwnd)
        self.setWindowOpacity(1.0)
        if not shot:
            self._syncing = False
            self.profile_card.set_busy(False)
            self.add_system(self.t("sync_no_game"))
            return
        self._sync_shot = shot
        self._sync_thread = QThread(self)
        self._sync_worker = AskWorker(self.brain, self.SYNC_QUESTION, self.profiles.active, None, shot)
        self._sync_worker.moveToThread(self._sync_thread)
        self._sync_thread.started.connect(self._sync_worker.run)
        self._sync_worker.done.connect(self._on_sync_done)      # bound method → runs on the GUI thread
        self._sync_worker.done.connect(self._sync_thread.quit)
        self._sync_thread.start()

    def _on_sync_done(self, ans: Answer):
        self._syncing = False
        self.profile_card.set_busy(False)
        if ans.error:
            self.add_system(self.t("err_generic"))
            return
        changes = self.profiles.apply_update(ans.profile_update or {})
        if ans.avatar_box:
            self._update_avatar(self._sync_shot, ans.avatar_box)
        if changes:
            self._show_changes(changes)
        else:
            self.add_system(self.t("sync_nothing") if ans.profile_update or ans.avatar_box
                            else self.t("sync_not_found"))
        self.refresh_profile_chip()

    def _on_done_main(self, ans: Answer):
        self._on_done(ans, self._pending_history)

    def _on_done(self, ans: Answer, history: History | None):
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
        if ans.avatar_box and getattr(self, "_question_shot", None):
            self._update_avatar(self._question_shot, ans.avatar_box)

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

    def _update_avatar(self, shot_jpeg: bytes, box: list) -> None:
        """Crop the player's own sprite (box from Claude, fractions of the image) into the portrait."""
        import io
        from PIL import Image
        try:
            img = Image.open(io.BytesIO(shot_jpeg)).convert("RGB")
            W, H = img.size
            x, y, w, h = box
            if not (0 <= x < 1 and 0 <= y < 1 and 0.005 < w < 0.5 and 0.01 < h < 0.6):
                return
            pad_w, pad_h = w * 0.25, h * 0.12
            left, top = max(0, (x - pad_w) * W), max(0, (y - pad_h) * H)
            right, bottom = min(W, (x + w + pad_w) * W), min(H, (y + h + pad_h) * H)
            crop = img.crop((int(left), int(top), int(right), int(bottom)))
            side = max(crop.size)
            square = Image.new("RGB", (side, side), crop.getpixel((0, 0)))
            square.paste(crop, ((side - crop.width) // 2, (side - crop.height) // 2))
            square = square.resize((128, 128), Image.LANCZOS)
            buf = io.BytesIO()
            square.save(buf, "PNG")
            self.profiles.set_avatar(buf.getvalue())
            self.refresh_profile_chip()
        except Exception:
            pass

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
        self.mic_btn.setProperty("active", "true" if state.startswith("listening") else "false")
        self.mic_btn.style().unpolish(self.mic_btn)
        self.mic_btn.style().polish(self.mic_btn)
        text = {"listening": self.t("listening"), "listening_click": self.t("listening_click"),
                "transcribing": self.t("transcribing"),
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
