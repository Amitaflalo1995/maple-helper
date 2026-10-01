"""Play tools: where to train, hit/damage calculator, build plan, quests, EXP meter, and two
quick checks (what to sell, what to buy). Everything reads the KB and the character; nothing touches
the game. The window is non-modal, so it can stay open beside the chat."""
from __future__ import annotations

import html
import math
import re
import time

from PySide6.QtCore import QEvent, QPoint, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QIcon, QPixmap, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (QButtonGroup, QCompleter, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QScrollArea, QStackedWidget, QTextBrowser, QVBoxLayout, QWidget)

from .. import bidi, buildplan, combat, guides, plan, quests
from ..i18n import I18n
from . import theme
from .controls import Section, Segmented, Stepper, rtl_buttons
from .glass import GlassDialog

PAGES = ("train", "calc", "build", "quests", "exp", "more")
MAX_QUESTS = 40


def clear(layout):
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w:
            w.hide()
            w.deleteLater()
        elif item.layout():
            clear(item.layout())


def tag(text: str, kind: str = "Tag") -> QLabel:
    lb = QLabel(text, objectName=kind)
    lb.setAlignment(Qt.AlignCenter)
    return lb


def scroll_page() -> tuple[QScrollArea, QVBoxLayout]:
    sc = QScrollArea()
    sc.setWidgetResizable(True)
    sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    body = QWidget(objectName="Feed")
    lay = QVBoxLayout(body)
    lay.setContentsMargins(0, 0, 6, 0)
    lay.setSpacing(14)
    sc.setWidget(body)
    return sc, lay


NAME_ROLE = Qt.UserRole + 1


class EntityPicker(QLineEdit):
    """A search box that opens a list of names with pictures; typing narrows it down.
    rows: (shown text, name to put in the box, picture path or None)."""
    picked = Signal()

    def __init__(self, rows: list[tuple[str, str, object]], placeholder: str, icon: int = 36):
        super().__init__()
        self.setPlaceholderText(placeholder)
        self.setClearButtonEnabled(True)
        model = QStandardItemModel(self)
        for shown, name, path in rows:
            item = QStandardItem(shown)
            item.setData(name, NAME_ROLE)
            if path:
                item.setIcon(QIcon(QPixmap(str(path)).scaled(icon, icon, Qt.KeepAspectRatio, Qt.SmoothTransformation)))
            item.setEditable(False)
            model.appendRow(item)
        comp = QCompleter(model, self)
        comp.setCompletionRole(NAME_ROLE)
        comp.setCaseSensitivity(Qt.CaseInsensitive)
        comp.setFilterMode(Qt.MatchContains)
        comp.setMaxVisibleItems(9)
        comp.popup().setIconSize(QSize(icon, icon))
        c = theme.P()
        bg = "#2C2C2E" if theme.MODE == "dark" else "#FFFFFF"
        comp.popup().setStyleSheet(
            f"QListView {{ background: {bg}; color: {c['text']}; border: 1px solid {c['stroke']}; border-radius: 10px;"
            f" padding: 4px; outline: none; }}"
            f"QListView::item {{ padding: 4px 6px; border-radius: 8px; color: {c['text']}; }}"
            f"QListView::item:selected, QListView::item:hover {{ background: rgba(255,149,51,0.22); color: {c['text']}; }}")
        comp.activated.connect(lambda *_: QTimer.singleShot(0, self._chosen))
        self.setCompleter(comp)
        self.returnPressed.connect(self.picked.emit)
        # a chevron says "this opens a list" before anyone clicks
        arrow = self.addAction(self._chevron(), QLineEdit.TrailingPosition)
        arrow.triggered.connect(self.open_list)
        self.setMinimumHeight(34)

    @staticmethod
    def _chevron() -> QIcon:
        from PySide6.QtGui import QColor, QPainter, QPen
        pm = QPixmap(20, 20)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(theme.ORANGE_DEEP), 2.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPolyline([QPoint(5, 8), QPoint(10, 13), QPoint(15, 8)])
        p.end()
        return QIcon(pm)

    def _chosen(self):
        self.setCursorPosition(0)              # a long name shows from its start
        self.picked.emit()

    def open_list(self):
        comp = self.completer()
        comp.setCompletionPrefix(self.text())
        comp.complete()

    def mousePressEvent(self, e):
        super().mousePressEvent(e)
        self.open_list()                      # a click shows the whole list, not only after typing

    def event(self, e):
        if e.type() == QEvent.KeyPress and e.key() == Qt.Key_Down and not self.completer().popup().isVisible():
            self.open_list()
            return True
        return super().event(e)


def monster_rows(kb) -> list[tuple[str, str, object]]:
    """Every monster once (the version that spawns on the most maps), lowest level first."""
    best: dict[str, combat.Monster] = {}
    for m in combat.monsters(kb):
        if combat.special_monster(m.name):
            continue
        if m.name not in best or sum(n for _, n in m.maps) > sum(n for _, n in best[m.name].maps):
            best[m.name] = m
    return [(f"{m.name}  ·  Lv. {m.level}", m.name, kb.picture(m.key))
            for m in sorted(best.values(), key=lambda m: (m.level, m.name))]


def map_rows(kb) -> list[tuple[str, str, object]]:
    """Every reachable map with its minimap: hunting grounds by monster level, then towns and the rest."""
    rows = []
    for k, e in kb.entities.items():
        if e.get("category") != "map":
            continue
        page = kb.page(k)
        where = re.search(r"\nLocation (.+)", page)
        place = where.group(1).split(" / ")[-1].strip() if where else ""
        if not combat.grind_map(f"{e['name']} {place}"):
            continue
        lv = re.search(r"\nMonster levels Lv (\d+)\s*[-–]\s*(\d+)", page)
        lo = int(lv.group(1)) if lv else 999
        bits = [e["name"]] + ([f"Lv. {lv.group(1)}-{lv.group(2)}"] if lv else []) + ([place] if place else [])
        rows.append((lo, e["name"], ("  ·  ".join(bits), e["name"], kb.picture(k))))
    rows.sort(key=lambda r: (r[0], r[1]))
    return [r[2] for r in rows]


class ToolsDialog(GlassDialog):
    sync_requested = Signal()                 # read level/EXP/stats from a screenshot (the chat does it)
    ask_requested = Signal(str, bool)          # question for the chat, with a fresh screenshot?
    tag_requested = Signal(str)                # tag an entity (monster, quest) in the chat
    guide_requested = Signal(str)              # open a guide in the guides window

    def __init__(self, kb, profiles, settings, lang: str, stylesheet: str, exp_meter: dict, page: str = "train"):
        self.t = t = I18n(lang or "he")
        super().__init__(t("tools"), t.rtl)
        self.kb, self.profiles, self.settings, self.meter = kb, profiles, settings, exp_meter
        self.setStyleSheet(stylesheet)
        self.resize(580, 800)
        rtl = t.rtl
        outer = QVBoxLayout(self.content)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)
        # the pages as chips, two rows of three so every label stays readable
        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(6)
        self.nav = QButtonGroup(self)
        for i, name in enumerate(PAGES):
            b = QPushButton(bidi.plain(t(f"tool_{name}"), rtl).replace("&", "&&"), objectName="Chip")   # "&" isn't a shortcut
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setProperty("page", name)
            self.nav.addButton(b, i)
            grid.addWidget(b, i // 3, i % 3)
        self.nav.idClicked.connect(self.show_page)
        outer.addLayout(grid)
        self.stack = QStackedWidget()
        outer.addWidget(self.stack, 1)
        self.pages = {}
        for name in PAGES:
            w = getattr(self, f"_page_{name}")()
            self.pages[name] = w
            self.stack.addWidget(w)
        rtl_buttons(self, rtl)
        self.show_page(PAGES.index(page) if page in PAGES else 0)

    # common -------------------------------------------------------------

    @property
    def c(self):
        return self.profiles.active

    def show_page(self, i: int):
        self.nav.button(i).setChecked(True)
        self.stack.setCurrentIndex(i)
        self.refresh(PAGES[i])

    def refresh(self, name: str | None = None):
        """Redraw a page (or the current one) from the character and the KB."""
        name = name or PAGES[self.stack.currentIndex()]
        getattr(self, f"_fill_{name}", lambda: None)()

    def profile_changed(self):
        """The chat read the profile again (level, EXP, stats): follow it."""
        self._load_stats()
        self.refresh()

    def sync_done(self, ok: bool):
        """A screenshot read ended: an EXP reading waiting for it takes the profile as it is now."""
        self.setWindowOpacity(1.0)
        if self.meter.get("pending"):
            if ok:
                self._meter_reading()
            else:
                self.meter.pop("pending")
                self._set(self.exp_status, self.t("exp_failed"))
        self.refresh()

    def _read_screen(self):
        """The chat reads the game from a screenshot; this window steps aside so it isn't in the picture."""
        self.setWindowOpacity(0.0)
        self.sync_requested.emit()
        QTimer.singleShot(1500, lambda: self.setWindowOpacity(1.0))

    def _p(self, text: str) -> str:
        return bidi.plain(text, self.t.rtl)

    def _html(self, text: str) -> str:
        d = "rtl" if self.t.rtl else "ltr"
        out = []
        for line in (text or "").split("\n"):
            if not line.strip():
                out.append("<p style='margin:0; font-size:5px;'>&nbsp;</p>")
                continue
            out.append(bidi.paragraph_html(line, d).replace("margin:0 0 4px 0;", "margin:0 0 3px 0; line-height:135%;"))
        return "".join(out)

    def _set(self, label: QLabel, text: str):
        label.setText(self._html(text))

    def _label(self, text: str, obj: str = "RowLabel", wrap: bool = True) -> QLabel:
        lb = QLabel(objectName=obj)
        lb.setTextFormat(Qt.RichText)
        lb.setWordWrap(wrap)
        self._set(lb, text)
        return lb

    def _no_character(self, lay):
        lay.addWidget(self._label(self.t("tool_no_char"), "RowHint"))

    # my stats (shared by "where to train" and the calculator) ------------

    def _stats_section(self) -> Section:
        t = self.t
        sec = Section(t("my_stats"), t.rtl)
        steppers = {}
        for key, hi in (("acc", 999), ("dmg_min", 99999), ("dmg_max", 99999)):
            st = Stepper(0, hi, 0)
            st.edit.setFixedWidth(64)
            st.valueChanged.connect(lambda v, k=key: self._set_stat(k, v))
            sec.add_row(t(f"stat_{key}"), st)
            steppers[key] = st
        self.__dict__.setdefault("_steppers", []).append(steppers)
        sec.add_widget(self._label(t("my_stats_hint"), "RowHint"))
        read = QPushButton(self._p(t("my_stats_read")), objectName="Link")
        read.setCursor(Qt.PointingHandCursor)
        read.clicked.connect(self._read_screen)
        sec.add_widget(read)
        return sec

    def _load_stats(self):
        s = (self.c.stats if self.c else {}) or {}
        for steppers in self.__dict__.get("_steppers", []):
            for key, st in steppers.items():
                st.blockSignals(True)
                st.setValue(int(s.get(key) or 0))
                st.blockSignals(False)

    def _set_stat(self, key: str, value: int):
        c = self.c
        if not c:
            return
        c.stats = {**(c.stats or {}), key: value} if value else {k: v for k, v in (c.stats or {}).items() if k != key}
        self.profiles.save()
        self._load_stats()                      # the other page's copy follows
        self.refresh()

    def _stats(self):
        s = (self.c.stats if self.c else {}) or {}
        acc = s.get("acc") or None
        dmg = (s.get("dmg_min") or 0, s.get("dmg_max") or 0)
        return acc, (dmg if dmg[0] > 0 else None)

    # where to train --------------------------------------------------------

    def _page_train(self):
        sc, lay = scroll_page()
        self.train_head = self._label("", "ToolHeader")
        lay.addWidget(self.train_head)
        self.train_list = QVBoxLayout()
        self.train_list.setSpacing(8)
        lay.addLayout(self.train_list)
        lay.addWidget(self._stats_section())
        lay.addStretch(1)
        self._load_stats()
        return sc

    def _fill_train(self):
        t, c = self.t, self.c
        clear(self.train_list)
        if not c:
            self.train_head.setText("")
            self._no_character(self.train_list)
            return
        acc, dmg = self._stats()
        magic = c.base_class == combat.MAGE
        rows = combat.spots(self.kb, c.level, acc, dmg, magic, n=6)
        bits = [t("lv_short", n=c.level)]
        if acc:
            bits.append(f"ACC {acc}")
        if dmg:
            bits.append(t("dmg_short", lo=dmg[0], hi=dmg[1]))
        head = " · ".join(bits)
        if not (acc and dmg):
            head += "\n" + t("train_need_stats")
        self._set(self.train_head, head)
        if not rows:
            self.train_list.addWidget(self._label(t("train_none"), "RowHint"))
            return
        for i, s in enumerate(rows):
            self.train_list.addWidget(self._spot_card(s, best=(i == 0)))

    def _spot_card(self, s: combat.Spot, best: bool) -> QFrame:
        t, c, m = self.t, self.c, s.monster
        card = QFrame(objectName="Card")
        row = QHBoxLayout(card)
        row.setContentsMargins(12, 10, 12, 10)
        row.setSpacing(12)
        pic = QLabel()
        pic.setFixedSize(52, 52)
        pic.setAlignment(Qt.AlignCenter)
        path = self.kb.picture(m.key)
        if path:
            pm = QPixmap(str(path))
            if not pm.isNull():
                pic.setPixmap(pm.scaled(52, 52, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        row.addWidget(pic, 0, Qt.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(3)
        name = QLabel(self._p(f"{m.name} · {t('lv_short', n=m.level)}"), objectName="CardName")
        col.addWidget(name)
        col.addWidget(self._label(s.map, "CardSub"))
        # two short rows of tags: why it's picked, then the numbers (one long row pushed the card wider)
        why, nums = QHBoxLayout(), QHBoxLayout()
        for line in (why, nums):
            line.setSpacing(5)
        if best:
            why.addWidget(tag(self._p(t("spot_best")), "TagAccent"))
        if s.recommended:
            why.addWidget(tag(self._p(t("spot_guide")), "TagGood"))
        if self._stats()[0]:
            why.addWidget(tag(self._p(t("spot_hit", pct=round(s.hit * 100))), "TagGood" if s.hit >= 0.999 else "TagWarn"))
        if s.hits:
            nums.addWidget(tag(self._p(t("spot_hits", n=s.hits)), "Tag"))
        nums.addWidget(tag(self._p(t("spot_exp", n=m.exp)), "Tag"))
        nums.addWidget(tag(self._p(t("spot_crowd", n=m.maps[0][1])), "Tag"))
        for line in (why, nums):
            if line.count():
                line.addStretch(1)
                col.addLayout(line)
        info = []
        if s.hit < 0.999 and self._stats()[0]:
            info.append(t("spot_acc_need", n=s.acc_needed))
        kills = combat.kills_to_level(self.kb, c.level, c.exp_pct, m)
        if kills:
            info.append(t("spot_kills", n=f"{kills:,}"))
        if info:
            col.addWidget(self._label("\n".join(info), "CardSub"))
        row.addLayout(col, 1)
        ask = QPushButton(self._p(t("ask_short")), objectName="Link")
        ask.setCursor(Qt.PointingHandCursor)
        ask.clicked.connect(lambda _=False, k=m.key: self.tag_requested.emit(k))
        row.addWidget(ask, 0, Qt.AlignVCenter)
        return card

    # calculator ----------------------------------------------------------

    def _page_calc(self):
        t = self.t
        sc, lay = scroll_page()
        rows = monster_rows(self.kb)
        self.calc_input = EntityPicker(rows, self._p(t("calc_placeholder", n=len(rows))))
        self.calc_input.picked.connect(self._fill_calc)
        lay.addWidget(self.calc_input)
        self.calc_box = QVBoxLayout()
        self.calc_box.setSpacing(12)
        lay.addLayout(self.calc_box)
        lay.addWidget(self._stats_section())
        lay.addStretch(1)
        self._load_stats()
        return sc

    def _calc_monster(self) -> combat.Monster | None:
        q = self.calc_input.text().strip().lower()
        if not q:
            spots = combat.spots(self.kb, self.c.level, n=1) if self.c else []
            return spots[0].monster if spots else None
        ms = combat.monsters(self.kb)
        exact = [m for m in ms if m.name.lower() == q]
        if exact:
            return min(exact, key=lambda m: -sum(n for _, n in m.maps))
        part = [m for m in ms if q in m.name.lower()]
        return min(part, key=lambda m: (len(m.name), m.level)) if part else None

    def _fill_calc(self):
        t, c = self.t, self.c
        clear(self.calc_box)
        if not c:
            self._no_character(self.calc_box)
            return
        m = self._calc_monster()
        if not m:
            self.calc_box.addWidget(self._label(t("calc_none"), "RowHint"))
            return
        acc, dmg = self._stats()
        magic = c.base_class == combat.MAGE
        sec = Section(f"{m.name} · {t('lv_short', n=m.level)}", t.rtl)
        nums = QHBoxLayout()
        for value, label in ((f"{m.hp:,}", "HP"), (f"{m.exp:,}", "EXP"), (str(m.avoid), "Avoid"),
                             (str(m.mdef if magic else m.pdef), "M.DEF" if magic else "P.DEF")):
            box = QVBoxLayout()
            box.setSpacing(0)
            v = QLabel(value, objectName="BigStat")
            v.setAlignment(Qt.AlignCenter)
            lb = QLabel(label, objectName="BigStatLabel")
            lb.setAlignment(Qt.AlignCenter)
            box.addWidget(v)
            box.addWidget(lb)
            nums.addLayout(box)
        holder = QWidget()
        holder.setLayout(nums)
        sec.add_widget(holder)
        need100 = combat.acc_needed(c.level, m.level, m.avoid)
        need90 = combat.acc_needed(c.level, m.level, m.avoid, 0.9)
        sec.add_row(t("calc_acc_need"), tag(f"{need100}", "TagAccent"), hint=t("calc_acc_need90", n=need90))
        if acc:
            hit = combat.hit_chance(acc, c.level, m.level, m.avoid)
            hint = ""
            if hit < 0.999:
                more = need100 - acc
                pts = math.ceil(more / combat.acc_per_point(c.base_class))
                hint = t("calc_more_acc", n=more, pts=pts, stat="INT" if magic else "DEX")
            sec.add_row(t("calc_hit"), tag(f"{round(hit * 100)}%", "TagGood" if hit >= 0.999 else "TagWarn"),
                        hint=hint)
        if dmg:
            hits, avg = combat.hits_to_kill(dmg[0], dmg[1], m, c.level, magic)
            sec.add_row(t("calc_hits"), tag(str(hits), "Tag"), hint=t("calc_hits_avg", n=f"{avg:.1f}"))
        if not (acc and dmg):
            sec.add_widget(self._label(t("calc_need_stats"), "RowHint"))
        # the same monster a few levels from now
        lv_rows = []
        for lv in (c.level - 5, c.level, c.level + 5):
            if lv >= 1:
                lv_rows.append(t("calc_at_level", lv=lv, n=combat.acc_needed(lv, m.level, m.avoid)))
        sec.add_widget(self._label("\n".join([t("calc_acc_by_level")] + ["• " + r for r in lv_rows]), "RowHint"))
        if m.maps:
            sec.add_widget(self._label("\n".join([t("calc_maps_head")] + ["• " + mp for mp, _ in m.maps[:3]]),
                                       "RowHint"))
        self.calc_box.addWidget(sec)

    # build ---------------------------------------------------------------

    def _page_build(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.build_head = self._label("", "ToolHeader")
        lay.addWidget(self.build_head)
        self.build_view = QTextBrowser(objectName="GuideText")
        self.build_view.setOpenLinks(False)
        self.build_view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        from .guides import ImageZoom
        self.build_zoom = ImageZoom(self.build_view)
        lay.addWidget(self.build_view, 1)
        self.build_guide_btn = QPushButton(self._p(self.t("build_open_guide")), objectName="Link")
        self.build_guide_btn.setCursor(Qt.PointingHandCursor)
        lay.addWidget(self.build_guide_btn, 0, (Qt.AlignRight if self.t.rtl else Qt.AlignLeft) | Qt.AlignAbsolute)
        self._build_key = None
        self.build_guide_btn.clicked.connect(lambda: self._build_key and self.guide_requested.emit(self._build_key))
        return w

    def _fill_build(self):
        t, c = self.t, self.c
        if not c:
            self._set(self.build_head, t("tool_no_char"))
            self.build_view.setHtml("")
            return
        key, tables = buildplan.tables(self.kb, c.base_class, c.job, c.level, t.lang)
        self._build_key = key
        self.build_guide_btn.setVisible(bool(key))
        self._set(self.build_head, t("build_head", job=c.job or c.base_class, n=c.level))
        if not tables:
            self.build_view.setHtml(f"<p>{t('build_none')}</p>")
            return
        he = t.lang != "en"
        icons = self._skill_icons()
        col = guides.NOTE_COLORS.get(theme.MODE, guides.NOTE_COLORS["light"])
        side = "dir='rtl' align='right'" if he else ""
        out = []
        for tb in tables:
            out.append(f"<h3 {side}>{guides._rich(tb.heading, he and bool(bidi._RTL.search(tb.heading)))}</h3>")
            cells = []
            for n, row in enumerate(tb.rows):
                bg = f" bgcolor='{col['head']}'" if n == 0 else (f" bgcolor='{col['note']}'" if n == tb.current else "")
                tagname = "th" if n == 0 else "td"
                cells.append("<tr>" + "".join(
                    f"<{tagname}{bg}><p {'dir=rtl align=right' if he and bidi._RTL.search(x) else ''} style='margin:0'>"
                    f"{self._with_skill_icon(x, icons) if tb.kind == 'sp' and n else ''}"
                    f"{guides._rich(x, he and bool(bidi._RTL.search(x)), 18)}</p></{tagname}>"
                    for i, x in enumerate(row)) + "</tr>")
            out.append(f"<table {side} width='100%' cellspacing='0' cellpadding='5' border='1' "
                       f"style='border-color: {col['line']}; border-style: solid; margin: 4px 0 12px 0;'>{''.join(cells)}</table>")
        self.build_view.setLayoutDirection(Qt.RightToLeft if he else Qt.LeftToRight)
        opt = self.build_view.document().defaultTextOption()
        opt.setTextDirection(Qt.RightToLeft if he else Qt.LeftToRight)
        self.build_view.document().setDefaultTextOption(opt)
        self.build_view.setHtml("\n".join(out))

    def _skill_icons(self) -> list[tuple[str, str]]:
        """(skill name, picture file URI), longest names first so "Power Strike" wins over "Power"."""
        if not hasattr(self, "_skills"):
            out = []
            for k, e in self.kb.entities.items():
                if e.get("category") == "skill":
                    path = self.kb.picture(k)
                    if path:
                        out.append((e["name"], path.as_uri()))
            self._skills = sorted(out, key=lambda x: -len(x[0]))
        return self._skills

    @staticmethod
    def _with_skill_icon(cell: str, icons: list[tuple[str, str]]) -> str:
        """Icons of the skills a table cell names ("Rush +1", "Power Strike 20, Slash Blast 3")."""
        if "[[img:" in cell:
            return ""
        found, taken = [], cell
        for name, uri in icons:
            if name in taken:
                found.append((cell.find(name), uri))
                taken = taken.replace(name, " " * len(name))
        return "".join(f"<img src='{uri}' height='20' style='vertical-align: middle'> "
                       for _, uri in sorted(found)[:3])

    # quests --------------------------------------------------------------

    def _page_quests(self):
        t = self.t
        sc, lay = scroll_page()
        self.q_mode = Segmented([(t("q_now"), "now"), (t("q_soon"), "soon"), (t("q_town"), "town")], "now", t.rtl)
        self.q_mode.changed.connect(lambda *_: self._fill_quests())
        lay.addWidget(self.q_mode, 0, Qt.AlignHCenter)
        self.q_head = self._label("", "ToolHeader")
        lay.addWidget(self.q_head)
        self.q_list = QVBoxLayout()
        self.q_list.setSpacing(8)
        lay.addLayout(self.q_list)
        lay.addStretch(1)
        return sc

    def _fill_quests(self):
        t, c = self.t, self.c
        clear(self.q_list)
        if not c:
            self.q_head.setText("")
            self._no_character(self.q_list)
            return
        r = quests.for_level(self.kb, c.level, c.base_class, c.job, c.quests_done)
        mode = self.q_mode.value()
        rows = r[mode]
        self._set(self.q_head, t(f"q_head_{mode}", n=len(rows), lv=c.level) +
                  ("\n" + t("q_done_count", n=r["done"]) if r["done"] else ""))
        if not rows:
            self.q_list.addWidget(self._label(t("q_none"), "RowHint"))
        for q in rows[:MAX_QUESTS]:
            self.q_list.addWidget(self._quest_card(q))

    def _picture_uri(self, kind: str, name: str) -> str | None:
        """The KB picture of a monster / item / NPC by its name, as a file URI."""
        n = name.strip().lower()
        if kind == "npc":
            key = self.kb._npc_by_name.get(n)
        elif kind == "item":
            key = self.kb._item_by_name.get(n)
        else:
            key = next((m.key for m in combat.monsters(self.kb) if m.name.lower() == n), None)
        path = self.kb.picture(key) if key else None
        return path.as_uri() if path else None

    def _thing_html(self, text: str) -> str:
        """ "Defeat Blue Snail x 10" / "Red Potion x 20" -> its picture, then the name (kept as one English block)."""
        m = re.fullmatch(r"(Defeat |Collect )?(.+?) x ([\d,]+)", text.strip())
        if not m:
            return html.escape(text)
        verb, name, n = m.groups()
        uri = self._picture_uri("monster" if verb == "Defeat " else "item", name) or \
            self._picture_uri("item" if verb == "Defeat " else "monster", name)
        img = f"<img src='{uri}' height='24' style='vertical-align: middle'>&nbsp;" if uri else ""
        # picture and name in one left-to-right unit, so in Hebrew the picture stays beside its own name
        return f"<span style='white-space: nowrap'>{bidi.LRE}{img}{html.escape(name)} x{n}{bidi.PDF}{bidi.RLM}</span>"

    def _things_label(self, head: str, things: list[str]) -> QLabel:
        rtl = self.t.rtl
        body = "&nbsp;&nbsp; ".join(self._thing_html(x) for x in things)
        lb = QLabel(f"<div {'dir=rtl' if rtl else ''}><b>{html.escape(head)}</b>&nbsp; {body}</div>", objectName="CardSub")
        lb.setTextFormat(Qt.RichText)
        lb.setWordWrap(True)
        return lb

    def _quest_card(self, q: quests.Quest) -> QFrame:
        t = self.t
        card = QFrame(objectName="Card")
        outer = QHBoxLayout(card)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(12)
        npc = QLabel()
        npc.setFixedSize(52, 60)
        npc.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        uri = self._picture_uri("npc", q.npc) if q.npc else None
        if uri:
            pm = QPixmap(QUrl(uri).toLocalFile())
            if not pm.isNull():
                npc.setPixmap(pm.scaled(52, 60, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        outer.addWidget(npc, 0, Qt.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(4)
        outer.addLayout(col, 1)
        top = QHBoxLayout()
        name = QLabel(self._p(q.name), objectName="CardName")
        name.setWordWrap(True)
        top.addWidget(name, 1)
        top.addWidget(tag(self._p(t("lv_short", n=q.level)), "Tag"))
        if q.exp:
            top.addWidget(tag(f"+{q.exp:,} EXP", "TagGood"))
        col.addLayout(top)
        where = [x for x in (q.npc, q.area) if x]
        if where:
            col.addWidget(self._label(" · ".join(where), "CardSub"))
        if q.needs:
            col.addWidget(self._things_label(t("q_needs_head"), q.needs[:4]))
        gets = q.rewards[:3]
        if gets or q.mesos:
            lb = self._things_label(t("q_gets_head"), gets)
            if q.mesos:
                lb.setText(lb.text().replace("</div>", f"&nbsp;&nbsp; {bidi.LRE}{q.mesos:,} mesos{bidi.PDF}</div>"))
            col.addWidget(lb)
        if q.after:
            col.addWidget(self._label(t("q_after", name=q.after), "RowHint"))
        acts = QHBoxLayout()
        done = QPushButton(self._p(t("q_mark_done")), objectName="Secondary")
        done.setCursor(Qt.PointingHandCursor)
        done.clicked.connect(lambda _=False, k=q.key: self._quest_done(k))
        acts.addWidget(done)
        ask = QPushButton(self._p(t("ask_short")), objectName="Link")
        ask.setCursor(Qt.PointingHandCursor)
        ask.clicked.connect(lambda _=False, k=q.key: self.tag_requested.emit(k))
        acts.addWidget(ask)
        acts.addStretch(1)
        col.addLayout(acts)
        return card

    def _quest_done(self, key: str):
        c = self.c
        if c and key not in c.quests_done:
            c.quests_done.append(key)
            self.profiles.save()
        self._fill_quests()

    # EXP meter -----------------------------------------------------------

    def _page_exp(self):
        t = self.t
        sc, lay = scroll_page()
        sec = Section(t("exp_title"), t.rtl)
        self.exp_now = self._label("", "RowLabel")
        sec.add_widget(self.exp_now)
        grid = QHBoxLayout()
        self.exp_cells = {}
        for key in ("per_hour", "pct_hour", "to_level"):
            box = QVBoxLayout()
            box.setSpacing(0)
            v = QLabel("–", objectName="BigStat")
            v.setAlignment(Qt.AlignCenter)
            lb = QLabel(self._p(t(f"exp_{key}")), objectName="BigStatLabel")
            lb.setAlignment(Qt.AlignCenter)
            box.addWidget(v)
            box.addWidget(lb)
            grid.addLayout(box)
            self.exp_cells[key] = v
        holder = QWidget()
        holder.setLayout(grid)
        sec.add_widget(holder)
        self.exp_status = self._label("", "RowHint")
        sec.add_widget(self.exp_status)
        btns = QHBoxLayout()
        self.exp_start = QPushButton(self._p(t("exp_start")), objectName="Primary")
        self.exp_start.setCursor(Qt.PointingHandCursor)
        self.exp_start.clicked.connect(self._meter_start)
        self.exp_measure = QPushButton(self._p(t("exp_measure")), objectName="Secondary")
        self.exp_measure.setCursor(Qt.PointingHandCursor)
        self.exp_measure.clicked.connect(self._meter_measure)
        btns.addWidget(self.exp_start)
        btns.addWidget(self.exp_measure)
        btns.addStretch(1)
        holder2 = QWidget()
        holder2.setLayout(btns)
        sec.add_widget(holder2)
        sec.add_widget(self._label(t("exp_hint"), "RowHint"))
        lay.addWidget(sec)
        lay.addStretch(1)
        return sc

    def _meter_start(self):
        c = self.c
        if not c:
            return
        self.meter[c.id] = {"start": None, "result": None}
        self.meter["pending"] = ("start", c.id)
        self._set(self.exp_status, self.t("exp_reading"))
        self._read_screen()

    def _meter_measure(self):
        c = self.c
        if not c or not (self.meter.get(c.id) or {}).get("start"):
            return
        self.meter["pending"] = ("end", c.id)
        self._set(self.exp_status, self.t("exp_reading"))
        self._read_screen()

    def _meter_reading(self):
        """A fresh level/EXP reading arrived (after the screenshot read the chat ran)."""
        what, cid = self.meter.pop("pending")
        c = self.c
        if not c or c.id != cid or c.exp_pct is None:
            return
        sample = (time.time(), c.level, c.exp_pct)
        m = self.meter.setdefault(cid, {"start": None, "result": None})
        if what == "start":
            m["start"], m["result"] = sample, None
        else:
            m["result"] = plan.exp_rate(self.kb, m["start"], sample)
            m["end"] = sample

    def _fill_exp(self):
        t, c = self.t, self.c
        if not c:
            self._set(self.exp_now, t("tool_no_char"))
            return
        pct = f"{c.exp_pct:.1f}%" if c.exp_pct is not None else "?"
        self._set(self.exp_now, t("exp_now", lv=c.level, pct=pct))
        m = self.meter.get(c.id) or {}
        r = m.get("result")
        for key, cell in self.exp_cells.items():
            v = (r or {}).get(key)
            if v is None:
                cell.setText("–")
            elif key == "per_hour":
                cell.setText(f"{v:,}")
            elif key == "pct_hour":
                cell.setText(f"{v}%")
            else:
                h, rest = divmod(int(v), 3600)
                cell.setText(f"{h}:{rest // 60:02d}")
        self.exp_measure.setEnabled(bool(m.get("start")))
        if self.meter.get("pending"):
            return
        if m.get("start") and not r:
            mins = max(0, round((time.time() - m["start"][0]) / 60))
            self._set(self.exp_status, t("exp_started", n=mins, pct=f"{m['start'][2]:.1f}%"))
        elif r:
            self._set(self.exp_status, t("exp_result", n=r["minutes"]))
        elif m.get("end"):
            self._set(self.exp_status, t("exp_no_gain"))
        else:
            self._set(self.exp_status, t("exp_idle"))

    # quick checks --------------------------------------------------------

    def _page_more(self):
        t = self.t
        sc, lay = scroll_page()
        sell = Section(t("sell_title"), t.rtl)
        sell.add_widget(self._label(t("sell_body"), "RowLabel"))
        go = QPushButton(self._p(t("sell_go")), objectName="Primary")
        go.setCursor(Qt.PointingHandCursor)
        go.clicked.connect(self._sell_check)
        sell.add_widget(go)
        lay.addWidget(sell)
        shop = Section(t("shop_title"), t.rtl)
        shop.add_widget(self._label(t("shop_body"), "RowLabel"))
        maps = map_rows(self.kb)
        self.shop_map = EntityPicker(maps, self._p(t("shop_map_ph", n=len(maps))), icon=40)
        self.shop_map.setMinimumWidth(280)
        shop.add_row(t("shop_where"), self.shop_map)
        self.shop_len = Segmented([("30", 30), ("60", 60), ("120", 120)], 60, t.rtl)
        shop.add_row(t("shop_minutes"), self.shop_len)
        go2 = QPushButton(self._p(t("shop_go")), objectName="Primary")
        go2.setCursor(Qt.PointingHandCursor)
        go2.clicked.connect(self._shopping)
        shop.add_widget(go2)
        lay.addWidget(shop)
        lay.addStretch(1)
        return sc

    def _sell_check(self):
        self.setWindowOpacity(0.0)           # the inventory must be in the screenshot, not this window
        self.ask_requested.emit(self.t("sell_q"), True)
        QTimer.singleShot(1500, lambda: self.setWindowOpacity(1.0))

    def _fill_more(self):
        c = self.c
        if c and not self.shop_map.text():
            best = combat.spots(self.kb, c.level, *self._stats(), magic=c.base_class == combat.MAGE, n=1)
            if best:
                self.shop_map.setText(best[0].map)
                self.shop_map.setCursorPosition(0)     # show the start of the map name

    def _shopping(self):
        where = self.shop_map.text().strip() or self.t("shop_here")
        self.ask_requested.emit(self.t("shop_q", map=where, n=self.shop_len.value()), False)
