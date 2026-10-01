"""A liquid-glass backdrop that works even with the system's transparency effects off.

The overlay excludes itself from screen capture, samples what is behind it
(the game), and repaints that as a frosted, color-saturated material a few
times a second. Sampling happens at quarter resolution, so it stays cheap.
"""
from __future__ import annotations

from PIL import ImageEnhance, ImageFilter
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QImage, QPixmap

from .. import osapi

SCALE = 0.25          # sample at quarter resolution
BLUR = 7              # at quarter scale ≈ 28px of real blur
SATURATION = 1.7      # iOS-style vibrancy: blurred colors get richer, not muddier
BRIGHTNESS = 0.78
INTERVAL_MS = 120


class GlassBackdrop(QObject):
    updated = Signal()

    def __init__(self, widget):
        super().__init__(widget)
        self.widget = widget
        self.pixmap: QPixmap | None = None
        self.timer = QTimer(self, interval=INTERVAL_MS, timeout=self.refresh)

    def start(self):
        self.refresh()
        self.timer.start()

    def stop(self):
        self.timer.stop()

    def refresh(self):
        w = self.widget
        if not w.isVisible():
            return
        dpr = w.devicePixelRatioF() if osapi.SCREEN_COORDS_ARE_PHYSICAL else 1.0
        g = w.geometry()
        try:
            img = osapi.grab_screen(round(g.x() * dpr), round(g.y() * dpr), round(g.width() * dpr),
                                     round(g.height() * dpr))
        except Exception:
            return
        small = img.resize((max(1, int(img.width * SCALE)), max(1, int(img.height * SCALE))))
        small = small.filter(ImageFilter.GaussianBlur(BLUR))
        small = ImageEnhance.Color(small).enhance(SATURATION)
        small = ImageEnhance.Brightness(small).enhance(BRIGHTNESS)
        data = small.tobytes("raw", "RGB")
        qimg = QImage(data, small.width, small.height, small.width * 3, QImage.Format_RGB888).copy()
        self.pixmap = QPixmap.fromImage(qimg)
        self.updated.emit()
        w.update()


# ---------------------------------------------------------------- shared painting

from PySide6.QtCore import QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen  # noqa: E402
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QToolButton, QVBoxLayout, QWidget  # noqa: E402

from . import theme  # noqa: E402

SHADOW = 12


def glass_path(widget, radius: float = None) -> QPainterPath:
    r = theme.RADIUS if radius is None else radius
    path = QPainterPath()
    path.addRoundedRect(QRectF(widget.rect()).adjusted(SHADOW + 0.5, SHADOW + 0.5, -SHADOW - 0.5, -SHADOW - 0.5), r, r)
    return path


def paint_glass(widget, backdrop: "GlassBackdrop | None", strength: float = 0.6, radius: float = None) -> None:
    """The one material every window uses: soft shadow, blurred backdrop, neutral tint, sheen, rim.
    strength (0.4–1.0) scales the tint: higher = more opaque, easier to read over busy scenes."""
    c = theme.P()
    r = theme.RADIUS if radius is None else radius
    p = QPainter(widget)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    for i in range(SHADOW, 0, -2):
        sh = QPainterPath()
        sh.addRoundedRect(QRectF(widget.rect()).adjusted(SHADOW - i, SHADOW - i + 3, -(SHADOW - i), -(SHADOW - i) + 3),
                          r + i, r + i)
        p.fillPath(sh, QColor(0, 0, 0, int(26 * (1 - i / SHADOW)) + 2))
    path = glass_path(widget, r)
    p.save()
    p.setClipPath(path)
    live = backdrop is not None and backdrop.pixmap is not None
    if live:
        p.drawPixmap(widget.rect(), backdrop.pixmap)
    base = c["glass_alpha"] if live else c["solid_alpha"]
    tint = QColor(*c["glass"])
    if live:
        # strength 0.6 = the designed glass; toward 1.0 more solid (readability), toward 0.4 clearer
        s = max(0.4, min(1.0, strength))
        base = base + (1 - base) * (s - 0.6) / 0.4 if s >= 0.6 else base * s / 0.6
    tint.setAlphaF(base)
    p.fillPath(path, tint)
    sheen = QLinearGradient(0, SHADOW, 0, SHADOW + min(170, widget.height()))
    sheen.setColorAt(0.0, QColor(255, 255, 255, c["sheen"]))
    sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
    p.fillPath(path, sheen)
    p.restore()
    rim = QLinearGradient(0, SHADOW, 0, widget.height() - SHADOW)
    rim.setColorAt(0.0, QColor(255, 255, 255, c["rim_top"]))
    rim.setColorAt(0.4, QColor(255, 255, 255, c["rim"]))
    rim.setColorAt(1.0, QColor(255, 255, 255, c["rim"] // 2))
    p.setPen(QPen(rim, 1))
    p.drawPath(path)
    p.end()


class _DragBar(QWidget):
    def __init__(self, win):
        super().__init__()
        self._win, self._grab = win, None

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._grab = e.globalPosition().toPoint() - self._win.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._grab is not None and e.buttons() & Qt.LeftButton:
            self._win.move(e.globalPosition().toPoint() - self._grab)

    def mouseReleaseEvent(self, e):
        self._grab = None


class GlassDialog(QDialog):
    """Frameless glass window with the app's own title bar (title + close). Put content in self.content."""

    def __init__(self, title: str, rtl: bool, show_in_captures: bool = False, closable: bool = True,
                 strength: float = 0.6):
        # on top like the chat and Settings, or a confirmation opened from Settings hides behind it
        super().__init__(None, Qt.FramelessWindowHint | Qt.Dialog | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle(title)
        self.setLayoutDirection(Qt.RightToLeft if rtl else Qt.LeftToRight)
        self._show_in_captures = show_in_captures
        self._strength = strength
        self.backdrop = GlassBackdrop(self)
        root = QVBoxLayout(self)
        root.setContentsMargins(SHADOW + 18, SHADOW + 10, SHADOW + 18, SHADOW + 16)
        root.setSpacing(8)
        bar = _DragBar(self)
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(0, 0, 0, 4)
        self.title_label = QLabel(title, objectName="Title")
        bl.addWidget(self.title_label)
        bl.addStretch(1)
        self.close_btn = QToolButton(objectName="IconClose", text=theme.ICON["close"])
        self.close_btn.setCursor(Qt.PointingHandCursor)
        self.close_btn.clicked.connect(self.reject)
        self.close_btn.setVisible(closable)
        bl.addWidget(self.close_btn)
        root.addWidget(bar)
        self.content = QWidget(objectName="Feed")
        root.addWidget(self.content, 1)

    def paintEvent(self, e):
        paint_glass(self, None)
