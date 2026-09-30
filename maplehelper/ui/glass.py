"""A liquid-glass backdrop that works even with Windows 'Transparency effects' off.

The overlay excludes itself from screen capture, samples what is behind it
(the game), and repaints that as a frosted, color-saturated material a few
times a second. Sampling happens at quarter resolution, so it stays cheap.
"""
from __future__ import annotations

from PIL import ImageEnhance, ImageFilter
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QImage, QPixmap

from .. import winapi

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
        dpr = w.devicePixelRatioF()
        g = w.geometry()
        try:
            img = winapi.grab_screen(round(g.x() * dpr), round(g.y() * dpr), round(g.width() * dpr),
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
