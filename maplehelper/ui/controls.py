"""iOS-style controls: switch, segmented control, grouped section rows."""
from __future__ import annotations

from PySide6.QtCore import Property, QEasingCurve, QPropertyAnimation, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (QAbstractButton, QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton,
                               QSizePolicy, QVBoxLayout, QWidget)

from .. import bidi
from . import theme


class Switch(QAbstractButton):
    """iOS switch: the knob slides with a critically damped ease; mirrors in RTL."""

    def __init__(self, checked: bool = False):
        super().__init__()
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.PointingHandCursor)
        self._pos = 1.0 if checked else 0.0
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(200)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self.toggled.connect(self._animate)

    def sizeHint(self):
        return QSize(46, 28)

    def _animate(self, on: bool):
        self._anim.stop()
        self._anim.setStartValue(self._pos)      # from the current on-screen value
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def get_knob(self):
        return self._pos

    def set_knob(self, v):
        self._pos = v
        self.update()

    knob = Property(float, get_knob, set_knob)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = 46, 28
        track = QRectF(0, (self.height() - h) / 2, w, h)
        off = QColor(120, 120, 128, 90) if theme.MODE == "dark" else QColor(120, 120, 128, 60)
        on = QColor(52, 199, 89)                       # iOS system green
        t = self._pos
        col = QColor(int(off.red() + (on.red() - off.red()) * t), int(off.green() + (on.green() - off.green()) * t),
                     int(off.blue() + (on.blue() - off.blue()) * t), int(off.alpha() + (255 - off.alpha()) * t))
        p.setPen(Qt.NoPen)
        p.setBrush(col)
        p.drawRoundedRect(track, h / 2, h / 2)
        rtl = self.layoutDirection() == Qt.RightToLeft
        x0, x1 = 2, w - h + 2
        x = x0 + (x1 - x0) * (1 - t if rtl else t)
        p.setBrush(QColor(0, 0, 0, 40))
        p.drawEllipse(QRectF(x, track.top() + 3, h - 4, h - 4))
        p.setBrush(QColor(255, 255, 255))
        p.drawEllipse(QRectF(x, track.top() + 2, h - 4, h - 4))


class Segmented(QFrame):
    """Segmented control: one capsule, the chosen segment lifted as a solid pill."""

    changed = Signal(object)

    def __init__(self, options: list[tuple[str, object]], current, rtl: bool):
        super().__init__(objectName="Segmented")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(2)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        for label, value in options:
            b = QPushButton(bidi.plain(label, rtl), objectName="Segment")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setProperty("value", value)
            b.setChecked(value == current)
            self.group.addButton(b)
            lay.addWidget(b, 1)
        self.group.buttonClicked.connect(lambda b: self.changed.emit(b.property("value")))

    def value(self):
        b = self.group.checkedButton()
        return b.property("value") if b else None


class Section(QFrame):
    """A grouped card of rows (iOS Settings): label on the leading side, control on the trailing side."""

    def __init__(self, header: str = "", rtl: bool = True):
        super().__init__()
        self.rtl = rtl
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)
        if header:
            h = QLabel(bidi.plain(header.upper() if not rtl else header, rtl), objectName="SectionHeader")
            outer.addWidget(h)
        self.card = QFrame(objectName="Group")
        self.rows = QVBoxLayout(self.card)
        self.rows.setContentsMargins(14, 4, 14, 4)
        self.rows.setSpacing(0)
        outer.addWidget(self.card)
        self._count = 0

    def add_row(self, label: str, control: QWidget | None = None, hint: str = "") -> QWidget:
        if self._count:
            sep = QFrame(objectName="Separator")
            sep.setFixedHeight(1)
            self.rows.addWidget(sep)
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 8, 0, 8)
        col = QVBoxLayout()
        col.setSpacing(1)
        lb = QLabel(bidi.plain(label, self.rtl), objectName="RowLabel")
        lb.setWordWrap(True)
        col.addWidget(lb)
        if hint:
            hl = QLabel(bidi.plain(hint, self.rtl), objectName="RowHint")
            hl.setWordWrap(True)
            col.addWidget(hl)
        lay.addLayout(col, 1)
        if control is not None:
            control.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
            lay.addWidget(control, 0, Qt.AlignVCenter)
        self.rows.addWidget(row)
        self._count += 1
        return row

    def add_widget(self, w: QWidget):
        if self._count:
            sep = QFrame(objectName="Separator")
            sep.setFixedHeight(1)
            self.rows.addWidget(sep)
        self.rows.addWidget(w)
        self._count += 1
