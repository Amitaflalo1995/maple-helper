"""The player's plan inside the chat: an EXP bar on the character card, one tip at a time, and a
"My plan" panel (where to train, the next job, stats, the job's guide, "What now?").

Everything comes from plan.py (the KB's guides), so it shows up instantly and costs no Claude usage;
tapping a line asks the chat for the details.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton, QToolButton, QVBoxLayout

from .. import bidi, plan


class ExpBar(QFrame):
    """A slim EXP bar with one line under it: '67% · 51,328 EXP left · ~734 Jr. Wraith'."""

    def __init__(self):
        super().__init__(objectName="ExpRow")
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 4, 0, 0)
        col.setSpacing(3)
        self.bar = QProgressBar(objectName="ExpBar")
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        col.addWidget(self.bar)
        self.text = QLabel(objectName="ExpText")
        col.addWidget(self.text)

    def show_progress(self, p: dict | None, t, rtl: bool):
        self.setVisible(p is not None)
        if not p:
            return
        self.bar.setValue(round(p["pct"] * 10))
        if p.get("kills"):
            text = t("exp_line_kills", pct=f"{p['pct']:g}", left=f"{p['left']:,}", n=f"{p['kills']:,}", mob=p["mob"])
        else:
            text = t("exp_line", pct=f"{p['pct']:g}", left=f"{p['left']:,}")
        self.text.setText(bidi.plain(text, rtl))
        self.text.setAlignment((Qt.AlignRight if rtl else Qt.AlignLeft) | Qt.AlignAbsolute)


class TipStrip(QFrame):
    """One tip under the character card; tap to ask about it, ✕ to hide it until the next level."""

    asked = Signal(str)
    dismissed = Signal(str)

    def __init__(self):
        super().__init__(objectName="InfoNote")
        from . import theme
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 6, 6, 6)
        row.setSpacing(8)
        self.icon = QLabel(theme.ICON["info"], objectName="InfoIcon")
        row.addWidget(self.icon, 0, Qt.AlignVCenter)
        self.text = QLabel(objectName="InfoText")
        self.text.setWordWrap(True)
        row.addWidget(self.text, 1)
        self.close_btn = QToolButton(objectName="Icon", text=theme.ICON["close"])
        self.close_btn.setCursor(Qt.PointingHandCursor)
        self.close_btn.clicked.connect(lambda: self.dismissed.emit(self._tip.kind) if self._tip else None)
        row.addWidget(self.close_btn, 0, Qt.AlignTop)
        self.setCursor(Qt.PointingHandCursor)
        self._tip = None
        self.hide()

    def show_tip(self, tip: plan.Tip | None, t, rtl: bool):
        self._tip = tip
        self.setVisible(tip is not None)
        if tip:
            self.setLayoutDirection(Qt.RightToLeft if rtl else Qt.LeftToRight)
            self.text.setText(bidi.plain(t(tip.key, **tip.args), rtl))
            self.close_btn.setToolTip(t("tip_hide"))

    def mouseReleaseEvent(self, e):
        if self._tip and e.button() == Qt.LeftButton:
            self.asked.emit(self._tip.question)


class PlanPanel(QFrame):
    """'My plan': where to train next, the next job, how to spend stats, the job guide, and 'What now?'."""

    asked = Signal(str)
    what_now = Signal()
    guide_requested = Signal(str)

    def __init__(self):
        super().__init__(objectName="Card")
        self.col = QVBoxLayout(self)
        self.col.setContentsMargins(14, 10, 14, 10)
        self.col.setSpacing(4)
        self.hide()

    def _clear(self):
        while self.col.count():
            item = self.col.takeAt(0)
            if item.widget():
                item.widget().hide()   # gone now, not at the next event loop
                item.widget().deleteLater()

    def _label(self, text: str, name: str, rtl: bool) -> QLabel:
        lb = QLabel(bidi.plain(text, rtl), objectName=name)
        lb.setWordWrap(True)
        lb.setAlignment((Qt.AlignRight if rtl else Qt.AlignLeft) | Qt.AlignAbsolute)
        return lb

    def _link(self, text: str, on_click, rtl: bool) -> QPushButton:
        b = QPushButton(bidi.plain(text, rtl), objectName="PlanLink")
        b.setStyleSheet(f"text-align: {'right' if rtl else 'left'};")
        b.setCursor(Qt.PointingHandCursor)
        b.clicked.connect(on_click)
        return b

    def fill(self, kb, c, t, rtl: bool):
        self._clear()
        self.setLayoutDirection(Qt.RightToLeft if rtl else Qt.LeftToRight)
        arrow = "›  "       # a mirrored glyph: Qt draws it pointing left in Hebrew
        self.col.addWidget(self._label(t("plan_title", name=c.name), "CardName", rtl))

        self.col.addWidget(self._label(t("plan_where"), "PlanHead", rtl))
        steps = plan.route(kb, c.level)
        for b, s in steps[:3]:
            text = t("plan_spot", lo=b.lo, hi=b.hi, map=s.map, mob=s.mob, lv=s.mob_level)
            self.col.addWidget(self._link(arrow + text, lambda _=False, m=s.map: self.asked.emit(t("plan_spot_q", map=m)),
                                          rtl))
        if not steps:
            self.col.addWidget(self._label(t("plan_no_route"), "CardSub", rtl))

        nxt = plan.next_job(c.base_class, c.job, c.level)
        self.col.addWidget(self._label(t("plan_job"), "PlanHead", rtl))
        if nxt:
            jobs, lv = nxt
            names = " / ".join(jobs)
            self.col.addWidget(self._link(arrow + t("plan_job_line", jobs=names, level=lv),
                                          lambda: self.asked.emit(t("tip_job_q", jobs=names, level=lv)), rtl))
        else:
            self.col.addWidget(self._label(t("plan_job_done"), "CardSub", rtl))

        main, second = plan.STATS.get(c.base_class, ("STR", "DEX"))
        self.col.addWidget(self._label(t("plan_stats"), "PlanHead", rtl))
        self.col.addWidget(self._label(t("plan_stats_line", main=main, second=second), "CardStat", rtl))

        guide = plan.class_guide(kb, c.base_class, c.job)
        row = QHBoxLayout()
        row.setContentsMargins(0, 8, 0, 0)
        row.setSpacing(8)
        if guide:
            g = QPushButton(bidi.plain(t("plan_guide", job=c.job if guide.startswith(
                "guide/" + c.job.lower().split()[0]) else c.base_class), rtl), objectName="Secondary")
            g.setCursor(Qt.PointingHandCursor)
            g.clicked.connect(lambda: self.guide_requested.emit(guide))
            row.addWidget(g)
        now = QPushButton(bidi.plain(t("plan_what_now"), rtl), objectName="Primary")
        now.setCursor(Qt.PointingHandCursor)
        now.clicked.connect(self.what_now.emit)
        row.addWidget(now)
        row.addStretch(1)
        self.col.addLayout(row)
