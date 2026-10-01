"""Branded notifications (instead of the Windows toast, which shows the host process name)."""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QPoint, Qt, QTimer
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QToolButton, QVBoxLayout, QWidget

from .. import bidi
from ..store import ASSETS
from . import theme
from .glass import SHADOW, paint_glass

MARGIN = 16
WIDTH = 360


class Toast(QWidget):
    """A small card in the bottom corner: logo, title, message. Never steals focus from the game."""

    _live: list["Toast"] = []

    def __init__(self, title: str, message: str, rtl: bool, font_family: str, timeout_ms: int = 5000):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_MacAlwaysShowToolWindow)   # the app is never frontmost on macOS
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setLayoutDirection(Qt.RightToLeft if rtl else Qt.LeftToRight)
        self.setFixedWidth(WIDTH + 2 * SHADOW)
        c = theme.P()
        self.setStyleSheet(f"""
            * {{ font-family: "{font_family}"; color: {c['text']}; }}
            #Card {{ background: transparent; border: none; }}
            #Accent {{ background: {theme.ORANGE}; border-radius: 2px; }}
            #Title {{ font-size: 14px; font-weight: 600; color: {c['text']}; }}
            #Body {{ font-size: 13px; color: {c['text']}; }}
            #Brand {{ font-size: 11px; color: {c['muted']}; }}
            QToolButton {{ background: transparent; border: none; color: {c['muted']}; font-size: 14px; }}
            QToolButton:hover {{ color: {c['text']}; }}
        """)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(SHADOW, SHADOW, SHADOW, SHADOW)
        card = QFrame(objectName="Card")
        outer.addWidget(card)
        row = QHBoxLayout(card)
        row.setContentsMargins(12, 12, 12, 12)
        row.setSpacing(12)

        accent = QFrame(objectName="Accent")
        accent.setFixedWidth(4)
        row.addWidget(accent)

        icon = QLabel()
        pm = QPixmap(str(ASSETS / "brand" / "icon-64.png"))
        if not pm.isNull():
            icon.setPixmap(pm.scaled(40, 40, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        row.addWidget(icon, 0, Qt.AlignTop)

        col = QVBoxLayout()
        col.setSpacing(3)
        brand = QLabel("Maple Helper", objectName="Brand")
        brand.setAlignment((Qt.AlignRight if rtl else Qt.AlignLeft) | Qt.AlignAbsolute)
        col.addWidget(brand)
        t = QLabel(bidi.plain(title, rtl), objectName="Title")
        t.setWordWrap(True)
        col.addWidget(t)
        if message:
            b = QLabel(bidi.plain(message, rtl), objectName="Body")
            b.setWordWrap(True)
            col.addWidget(b)
        row.addLayout(col, 1)

        close = QToolButton(text="✕")
        close.setCursor(Qt.PointingHandCursor)
        close.clicked.connect(self.dismiss)
        row.addWidget(close, 0, Qt.AlignTop)

        self._timer = QTimer(self, singleShot=True, interval=timeout_ms, timeout=self.dismiss)

    def show_toast(self):
        self.adjustSize()
        screen = QGuiApplication.primaryScreen().availableGeometry()
        x = screen.right() - self.width() - MARGIN + SHADOW
        y = screen.bottom() - self.height() - MARGIN + SHADOW
        # stack above toasts that are still visible
        for other in Toast._live:
            if other.isVisible():
                y = min(y, other.y() - self.height() - 8)
        Toast._live.append(self)
        self.setWindowOpacity(0.0)
        self.move(QPoint(x, y + 12))
        self.show()
        self._anim(1.0, QPoint(x, y))
        self._timer.start()

    def _anim(self, opacity: float, pos: QPoint, on_done=None):
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(220)
        self._fade.setEndValue(opacity)
        self._fade.setEasingCurve(QEasingCurve.OutCubic)
        self._slide = QPropertyAnimation(self, b"pos", self)
        self._slide.setDuration(220)
        self._slide.setEndValue(pos)
        self._slide.setEasingCurve(QEasingCurve.OutCubic)
        if on_done:
            self._fade.finished.connect(on_done)
        self._fade.start()
        self._slide.start()

    def dismiss(self):
        self._timer.stop()
        if self in Toast._live:
            Toast._live.remove(self)
        self._anim(0.0, QPoint(self.x(), self.y() + 12), self.close)

    def mouseReleaseEvent(self, e):
        self.dismiss()

    def paintEvent(self, e):
        paint_glass(self, None, radius=18)


def notify(title: str, message: str = "", rtl: bool = True, font_family: str | None = None, timeout_ms: int = 5000):
    t = Toast(title, message, rtl, font_family or theme.FONT_FAMILY, timeout_ms)
    t.show_toast()
    return t
