"""Play tools: where to train, hit/damage calculator, build plan, quests, timers, EXP meter, and two
quick checks (what to sell, what to buy). Everything reads the KB and the character; nothing touches
the game. The window is non-modal, so it can stay open beside the chat."""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QStringListModel, Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QButtonGroup, QCompleter, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QScrollArea, QStackedWidget, QTextBrowser, QVBoxLayout, QWidget)

from .. import bidi, buildplan, combat, guides, plan, quests
from .. import timers as timers_mod
from ..i18n import I18n
from . import theme
from .controls import Section, Segmented, Stepper, rtl_buttons
from .glass import GlassDialog

PAGES = ("train", "calc", "build", "quests", "timers", "exp", "more")
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


class ToolsDialog(GlassDialog):
    sync_requested = Signal()                 # read level/EXP/stats from a screenshot (the chat does it)
    ask_requested = Signal(str, bool)          # question for the chat, with a fresh screenshot?
    tag_requested = Signal(str)                # tag an entity (monster, quest) in the chat
    guide_requested = Signal(str)              # open a guide in the guides window

    def __init__(self, kb, profiles, settings, lang: str, stylesheet: str, timers, exp_meter: dict,
                 page: str = "train"):
        self.t = t = I18n(lang or "he")
        super().__init__(t("tools"), t.rtl)
        self.kb, self.profiles, self.settings, self.timers, self.meter = kb, profiles, settings, timers, exp_meter
        self.setStyleSheet(stylesheet)
        self.resize(580, 800)
        rtl = t.rtl
        outer = QVBoxLayout(self.content)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)
        # the pages as chips, two short rows so every label stays readable
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
            grid.addWidget(b, i // 4, i % 4)
        self.nav.idClicked.connect(self.show_page)
        outer.addLayout(grid)
        self.stack = QStackedWidget()
        outer.addWidget(self.stack, 1)
        self.pages = {}
        for name in PAGES:
            w = getattr(self, f"_page_{name}")()
            self.pages[name] = w
            self.stack.addWidget(w)
        timers.changed.connect(self._timers_tick)
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
                self.exp_status.setText(self._p(self.t("exp_failed")))
        self.refresh()

    def _read_screen(self):
        """The chat reads the game from a screenshot; this window steps aside so it isn't in the picture."""
        self.setWindowOpacity(0.0)
        self.sync_requested.emit()
        QTimer.singleShot(1500, lambda: self.setWindowOpacity(1.0))

    def _p(self, text: str) -> str:
        return bidi.plain(text, self.t.rtl)

    def _label(self, text: str, obj: str = "RowLabel", wrap: bool = True) -> QLabel:
        lb = QLabel(self._p(text), objectName=obj)
        lb.setWordWrap(wrap)
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
        hint = QLabel(self._p(t("my_stats_hint")), objectName="RowHint")
        hint.setWordWrap(True)
        sec.add_widget(hint)
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
        self.train_head.setText(self._p(head))
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
        where = QLabel(self._p(t("spot_where", map=s.map, n=m.maps[0][1])), objectName="CardSub")
        where.setWordWrap(True)
        col.addWidget(where)
        tags = QHBoxLayout()
        tags.setSpacing(5)
        if best:
            tags.addWidget(tag(self._p(t("spot_best")), "TagAccent"))
        if s.recommended:
            tags.addWidget(tag(self._p(t("spot_guide")), "TagGood"))
        if self._stats()[0]:
            tags.addWidget(tag(self._p(t("spot_hit", pct=round(s.hit * 100))), "TagGood" if s.hit >= 0.999 else "TagWarn"))
        if s.hits:
            tags.addWidget(tag(self._p(t("spot_hits", n=s.hits)), "Tag"))
        tags.addWidget(tag(self._p(t("spot_exp", n=m.exp)), "Tag"))
        tags.addStretch(1)
        col.addLayout(tags)
        info = []
        if s.hit < 0.999 and self._stats()[0]:
            info.append(t("spot_acc_need", n=s.acc_needed))
        kills = combat.kills_to_level(self.kb, c.level, c.exp_pct, m)
        if kills:
            info.append(t("spot_kills", n=f"{kills:,}"))
        if info:
            sub = QLabel(self._p(" · ".join(info)), objectName="CardSub")
            sub.setWordWrap(True)
            col.addWidget(sub)
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
        self.calc_input = QLineEdit()
        self.calc_input.setPlaceholderText(self._p(t("calc_placeholder")))
        self.calc_input.setClearButtonEnabled(True)
        names = sorted({m.name for m in combat.monsters(self.kb)})
        comp = QCompleter(QStringListModel(names, self), self)
        comp.setCaseSensitivity(Qt.CaseInsensitive)
        comp.setFilterMode(Qt.MatchContains)
        self.calc_input.setCompleter(comp)
        comp.activated.connect(lambda *_: self._fill_calc())
        self.calc_input.returnPressed.connect(self._fill_calc)
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
        sec.add_widget(self._label(" · ".join(lv_rows), "RowHint"))
        if m.maps:
            sec.add_widget(self._label(t("calc_maps", maps=", ".join(mp for mp, _ in m.maps[:3])), "RowHint"))
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
            self.build_head.setText(self._p(t("tool_no_char")))
            self.build_view.setHtml("")
            return
        key, tables = buildplan.tables(self.kb, c.base_class, c.job, c.level, t.lang)
        self._build_key = key
        self.build_guide_btn.setVisible(bool(key))
        self.build_head.setText(self._p(t("build_head", job=c.job or c.base_class, n=c.level)))
        if not tables:
            self.build_view.setHtml(f"<p>{t('build_none')}</p>")
            return
        he = t.lang != "en"
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
                    f"{guides._rich(x, he and bool(bidi._RTL.search(x)), 18)}</p></{tagname}>"
                    for i, x in enumerate(row)) + "</tr>")
            out.append(f"<table {side} width='100%' cellspacing='0' cellpadding='5' border='1' "
                       f"style='border-color: {col['line']}; border-style: solid; margin: 4px 0 12px 0;'>{''.join(cells)}</table>")
        self.build_view.setLayoutDirection(Qt.RightToLeft if he else Qt.LeftToRight)
        opt = self.build_view.document().defaultTextOption()
        opt.setTextDirection(Qt.RightToLeft if he else Qt.LeftToRight)
        self.build_view.document().setDefaultTextOption(opt)
        self.build_view.setHtml("\n".join(out))

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
        self.q_head.setText(self._p(t(f"q_head_{mode}", n=len(rows), lv=c.level) +
                                    (" · " + t("q_done_count", n=r["done"]) if r["done"] else "")))
        if not rows:
            self.q_list.addWidget(self._label(t("q_none"), "RowHint"))
        for q in rows[:MAX_QUESTS]:
            self.q_list.addWidget(self._quest_card(q))

    def _quest_card(self, q: quests.Quest) -> QFrame:
        t = self.t
        card = QFrame(objectName="Card")
        col = QVBoxLayout(card)
        col.setContentsMargins(12, 10, 12, 10)
        col.setSpacing(4)
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
            col.addWidget(self._label(t("q_needs", what=" · ".join(q.needs[:4])), "CardSub"))
        gets = ([f"{q.mesos:,} mesos"] if q.mesos else []) + q.rewards[:3]
        if gets:
            col.addWidget(self._label(t("q_gets", what=" · ".join(gets)), "CardSub"))
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

    # timers --------------------------------------------------------------

    def _page_timers(self):
        t = self.t
        sc, lay = scroll_page()
        self.run_sec = Section(t("timers_running"), t.rtl)
        self.run_box = QVBoxLayout()
        holder = QWidget()
        holder.setLayout(self.run_box)
        self.run_sec.add_widget(holder)
        lay.addWidget(self.run_sec)
        self.preset_sec = Section(t("timers_presets"), t.rtl)
        self.preset_grid = QGridLayout()
        self.preset_grid.setSpacing(8)
        holder2 = QWidget()
        holder2.setLayout(self.preset_grid)
        self.preset_sec.add_widget(holder2)
        lay.addWidget(self.preset_sec)
        add = Section(t("timers_new"), t.rtl)
        self.t_name = QLineEdit()
        self.t_name.setPlaceholderText(self._p(t("timers_name_ph")))
        self.t_time = QLineEdit()
        self.t_time.setPlaceholderText("3:20")
        self.t_time.setFixedWidth(90)
        self.t_time.setAlignment(Qt.AlignCenter)
        row = QHBoxLayout()
        row.addWidget(self.t_name, 1)
        row.addWidget(self.t_time)
        go = QPushButton(self._p(t("timers_add")), objectName="Primary")
        go.setCursor(Qt.PointingHandCursor)
        go.clicked.connect(self._add_timer)
        self.t_time.returnPressed.connect(self._add_timer)
        row.addWidget(go)
        holder3 = QWidget()
        holder3.setLayout(row)
        add.add_widget(holder3)
        self.t_error = self._label("", "RowHint")
        add.add_widget(self.t_error)
        add.add_widget(self._label(t("timers_hint"), "RowHint"))
        lay.addWidget(add)
        lay.addStretch(1)
        return sc

    def _presets(self) -> list[dict]:
        return self.settings["timer_presets"] or [dict(p) for p in timers_mod.DEFAULT_PRESETS]

    def _fill_timers(self):
        t = self.t
        clear(self.preset_grid)
        for i, p in enumerate(self._presets()):
            name = t(f"timer_{p['name'].lower()}") if p["name"] in ("Buff", "Potions", "Boss") else p["name"]
            b = QPushButton(self._p(f"{name} · {timers_mod.clock(p['seconds'])}"), objectName="Secondary")
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, n=name, s=p["seconds"]: self.timers.start(n, s))
            x = QPushButton(theme.ICON["close"], objectName="Link")
            x.setStyleSheet(f"font-family: '{theme.ICON_FONT}'; font-size: 10px; min-height: 20px;")
            x.setCursor(Qt.PointingHandCursor)
            x.setToolTip(t("timers_remove"))
            x.clicked.connect(lambda _=False, idx=i: self._remove_preset(idx))
            cell = QHBoxLayout()
            cell.setSpacing(2)
            cell.addWidget(b, 1)
            cell.addWidget(x)
            self.preset_grid.addLayout(cell, i // 2, i % 2)
        self._timers_tick()

    def _timers_tick(self):
        if not hasattr(self, "run_box"):
            return
        t = self.t
        running = self.timers.running
        if [r.id for r in running] != getattr(self, "_run_ids", None):
            self._run_ids = [r.id for r in running]
            clear(self.run_box)
            self._run_labels = {}
            if not running:
                self.run_box.addWidget(self._label(t("timers_none"), "RowHint"))
            for r in running:
                line = QHBoxLayout()
                name = QLabel(self._p(r.name), objectName="CardName")
                line.addWidget(name, 1)
                left = QLabel("", objectName="BigStat")
                line.addWidget(left)
                again = QPushButton(theme.ICON["refresh"], objectName="Link")
                again.setStyleSheet(f"font-family: '{theme.ICON_FONT}';")
                again.setToolTip(t("timers_restart"))
                again.clicked.connect(lambda _=False, i=r.id: self.timers.restart(i))
                stop = QPushButton(theme.ICON["close"], objectName="LinkDanger")
                stop.setStyleSheet(f"font-family: '{theme.ICON_FONT}';")
                stop.setToolTip(t("timers_stop"))
                stop.clicked.connect(lambda _=False, i=r.id: self.timers.stop(i))
                for b in (again, stop):
                    b.setCursor(Qt.PointingHandCursor)
                    line.addWidget(b)
                holder = QWidget()
                holder.setLayout(line)
                self.run_box.addWidget(holder)
                self._run_labels[r.id] = left
        for r in running:
            lb = self._run_labels.get(r.id)
            if lb:
                lb.setText(timers_mod.clock(r.left()) if r.ends else "✓")

    def _add_timer(self):
        t = self.t
        secs = timers_mod.parse_clock(self.t_time.text())
        name = self.t_name.text().strip()
        if not secs or not name:
            self.t_error.setText(self._p(t("timers_bad")))
            return
        self.t_error.setText("")
        presets = [p for p in self._presets() if p["name"] != name] + [{"name": name, "seconds": secs}]
        self.settings["timer_presets"] = presets[-8:]
        self.timers.start(name, secs)
        self.t_name.clear()
        self.t_time.clear()
        self._fill_timers()

    def _remove_preset(self, i: int):
        presets = self._presets()
        if 0 <= i < len(presets):
            presets.pop(i)
            self.settings["timer_presets"] = presets
        self._fill_timers()

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
        self.exp_status.setText(self._p(self.t("exp_reading")))
        self._read_screen()

    def _meter_measure(self):
        c = self.c
        if not c or not (self.meter.get(c.id) or {}).get("start"):
            return
        self.meter["pending"] = ("end", c.id)
        self.exp_status.setText(self._p(self.t("exp_reading")))
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
            self.exp_now.setText(self._p(t("tool_no_char")))
            return
        pct = f"{c.exp_pct:.1f}%" if c.exp_pct is not None else "?"
        self.exp_now.setText(self._p(t("exp_now", lv=c.level, pct=pct)))
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
            self.exp_status.setText(self._p(t("exp_started", n=mins, pct=f"{m['start'][2]:.1f}%")))
        elif r:
            self.exp_status.setText(self._p(t("exp_result", n=r["minutes"])))
        elif m.get("end"):
            self.exp_status.setText(self._p(t("exp_no_gain")))
        else:
            self.exp_status.setText(self._p(t("exp_idle")))

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
        self.shop_map = QLineEdit()
        self.shop_map.setPlaceholderText(self._p(t("shop_map_ph")))
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


class TimerBar(QWidget):
    """The running timers as chips under the character card: tap to restart, ✕ to close."""

    def __init__(self, timers, t):
        super().__init__()
        self.timers, self.t = timers, t
        self.lay = QHBoxLayout(self)
        self.lay.setContentsMargins(2, 0, 2, 0)
        self.lay.setSpacing(6)
        self._ids = None
        self._chips = {}
        timers.changed.connect(self.redraw)
        self.redraw()

    def redraw(self):
        running = self.timers.running
        self.setVisible(bool(running))
        if [r.id for r in running] != self._ids:
            self._ids = [r.id for r in running]
            clear(self.lay)
            self._chips = {}
            for r in running:
                chip = QPushButton(objectName="TimerChip")
                chip.setCursor(Qt.PointingHandCursor)
                chip.setToolTip(self.t("timers_chip_tip"))
                chip.clicked.connect(lambda _=False, i=r.id: self.timers.restart(i))
                x = QPushButton(theme.ICON["close"], objectName="Link")
                x.setStyleSheet(f"font-family: '{theme.ICON_FONT}'; font-size: 9px; min-height: 18px; padding: 0 2px;")
                x.setCursor(Qt.PointingHandCursor)
                x.clicked.connect(lambda _=False, i=r.id: self.timers.stop(i))
                self.lay.addWidget(chip)
                self.lay.addWidget(x)
                self._chips[r.id] = chip
            self.lay.addStretch(1)
        for r in running:
            chip = self._chips.get(r.id)
            if not chip:
                continue
            done = not r.ends
            chip.setObjectName("TimerChipDone" if done else "TimerChip")
            chip.setText(f"{r.name} · " + (self.t("timers_done_short") if done else timers_mod.clock(r.left())))
            chip.style().unpolish(chip)
            chip.style().polish(chip)
