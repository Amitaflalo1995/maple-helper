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
        self.header = None
        if header:
            self.header = QLabel(objectName="SectionHeader")
            self.set_header(header)
            outer.addWidget(self.header)
        self.card = QFrame(objectName="Group")
        self.rows = QVBoxLayout(self.card)
        self.rows.setContentsMargins(14, 4, 14, 4)
        self.rows.setSpacing(0)
        outer.addWidget(self.card)
        self._count = 0

    def set_header(self, header: str) -> None:
        if self.header is not None:
            self.header.setText(bidi.plain(header.upper() if not self.rtl else header, self.rtl))

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


def track_slider(slider, rtl: bool) -> None:
    """Qt stylesheets always paint 'sub-page' on the visual left. In a mirrored (RTL) slider the
    filled part must grow from the right, so the two track colors swap sides."""
    if not rtl:
        return
    track = "rgba(255,255,255,0.22)" if theme.MODE == "dark" else "rgba(0,0,0,0.13)"
    slider.setStyleSheet(f"""
        QSlider::sub-page:horizontal {{ background: {track}; border-radius: 3px; }}
        QSlider::add-page:horizontal {{ background: {theme.ORANGE}; border-radius: 3px; }}
    """)


# ---------------------------------------------------------------- pop-up button (replaces QComboBox)

from PySide6.QtCore import QPoint, QPointF  # noqa: E402
from PySide6.QtGui import QAction, QPainterPath, QPen  # noqa: E402
from PySide6.QtWidgets import QMenu  # noqa: E402


class Select(QPushButton):
    """macOS-style pop-up button: shows the value with ⌃⌄ chevrons; opens a rounded glass menu
    anchored to itself, the current choice checked. API mirrors the bits of QComboBox we use."""

    currentIndexChanged = Signal(int)
    picked = Signal(int)          # only when the user chooses from the menu

    def __init__(self, items: list[str] | None = None):
        super().__init__(objectName="Select")
        self.setCursor(Qt.PointingHandCursor)
        self._items: list[str] = []
        self._index = -1
        self.clicked.connect(self._open)
        if items:
            self.addItems(items)

    # QComboBox-compatible surface
    def addItems(self, items):
        self._items.extend(items)
        if self._index < 0 and self._items:
            self.setCurrentIndex(0)
        self.updateGeometry()

    def clear(self):
        self._items, self._index = [], -1
        self.setText("")

    def count(self):
        return len(self._items)

    def currentText(self):
        return self._items[self._index] if 0 <= self._index < len(self._items) else ""

    def setCurrentIndex(self, i: int):
        if 0 <= i < len(self._items) and i != self._index:
            self._index = i
            self.setText(self._items[i])
            self.currentIndexChanged.emit(i)

    def setCurrentText(self, text: str):
        if text in self._items:
            self.setCurrentIndex(self._items.index(text))

    def sizeHint(self):
        s = super().sizeHint()
        longest = max((self.fontMetrics().horizontalAdvance(t) for t in self._items), default=40)
        return s.expandedTo(QSize(longest + 48, 30))

    def _open(self):
        menu = QMenu(self)
        menu.setWindowFlags(menu.windowFlags() | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        menu.setAttribute(Qt.WA_TranslucentBackground)
        menu.setLayoutDirection(self.layoutDirection())
        for i, t in enumerate(self._items):
            a = QAction(t, menu, checkable=True, checked=(i == self._index))
            a.triggered.connect(lambda _=False, i=i: (self.setCurrentIndex(i), self.picked.emit(i)))
            menu.addAction(a)
        if 0 <= self._index < len(self._items):
            menu.setActiveAction(menu.actions()[self._index])
        # open over the button so the current item lines up with it (macOS behaviour)
        rtl = self.layoutDirection() == Qt.RightToLeft
        anchor = self.mapToGlobal(QPoint(self.width() if rtl else 0, 0))
        menu.adjustSize()
        x = anchor.x() - menu.width() if rtl else anchor.x()
        menu.exec(QPoint(x, anchor.y()))

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rtl = self.layoutDirection() == Qt.RightToLeft
        cx = 14 if rtl else self.width() - 14          # chevrons on the trailing side
        cy = self.height() / 2
        col = QColor(235, 235, 245, 160) if theme.MODE == "dark" else QColor(60, 60, 67, 160)
        p.setPen(QPen(col, 1.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        up, down = QPainterPath(), QPainterPath()
        up.moveTo(QPointF(cx - 3.5, cy - 2))
        up.lineTo(QPointF(cx, cy - 5.5))
        up.lineTo(QPointF(cx + 3.5, cy - 2))
        down.moveTo(QPointF(cx - 3.5, cy + 2))
        down.lineTo(QPointF(cx, cy + 5.5))
        down.lineTo(QPointF(cx + 3.5, cy + 2))
        p.drawPath(up)
        p.drawPath(down)


class Stepper(QFrame):
    """iOS-style stepper: − value +. Hold a button to repeat; the value can also be typed."""

    valueChanged = Signal(int)

    def __init__(self, lo: int, hi: int, value: int):
        super().__init__(objectName="Stepper")
        from PySide6.QtGui import QIntValidator
        from PySide6.QtWidgets import QLineEdit, QToolButton
        self.lo, self.hi, self._v = lo, hi, value
        lay = QHBoxLayout(self)
        lay.setContentsMargins(2, 1, 2, 1)
        lay.setSpacing(0)
        self.minus = QToolButton(objectName="StepBtn", text="−")
        self.plus = QToolButton(objectName="StepBtn", text="+")
        for b, d in ((self.minus, -1), (self.plus, 1)):
            b.setCursor(Qt.PointingHandCursor)
            b.setAutoRepeat(True)
            b.setAutoRepeatDelay(350)
            b.setAutoRepeatInterval(60)
            b.clicked.connect(lambda _=False, d=d: self.setValue(self._v + d))
        self.edit = QLineEdit(str(value), objectName="StepValue")
        self.edit.setValidator(QIntValidator(lo, hi, self))
        self.edit.setAlignment(Qt.AlignCenter)
        self.edit.setFixedWidth(46)
        self.edit.textEdited.connect(self._typed)
        self.edit.editingFinished.connect(lambda: self.edit.setText(str(self._v)))
        # minus sits on the leading side, plus on the trailing side (mirrors in RTL)
        lay.addWidget(self.minus)
        lay.addWidget(self.edit)
        lay.addWidget(self.plus)
        self._sync()

    def value(self) -> int:
        return self._v

    def setMinimum(self, lo: int):
        """Raise/lower the floor; a value below it moves up to it (and emits)."""
        self.lo = lo
        from PySide6.QtGui import QIntValidator
        self.edit.setValidator(QIntValidator(lo, self.hi, self))
        if self._v < lo:
            self.setValue(lo)
        self._sync()

    def setValue(self, v: int):
        v = max(self.lo, min(self.hi, int(v)))
        if v != self._v:
            self._v = v
            self.edit.setText(str(v))
            self._sync()
            self.valueChanged.emit(v)

    def _typed(self, text: str):
        if text.isdigit():
            v = max(self.lo, min(self.hi, int(text)))
            if v != self._v:
                self._v = v
                self._sync()
                self.valueChanged.emit(v)

    def _sync(self):
        self.minus.setEnabled(self._v > self.lo)
        self.plus.setEnabled(self._v < self.hi)


def rtl_buttons(root, rtl: bool) -> None:
    """Qt lays push-button text out left-to-right whatever the widget direction, which throws
    final punctuation ("!", "?") to the wrong side. Re-mark every button label for RTL."""
    if not rtl:
        return
    for b in root.findChildren(QPushButton):
        t = b.text()
        if t and not t.startswith("\u200f") and b.objectName() not in ("Select",):
            b.setText(bidi.plain(t, True))
