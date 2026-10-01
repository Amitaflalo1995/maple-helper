"""Onboarding (mandatory, no skipping), character editor and settings."""
from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QButtonGroup, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QScrollArea, QStackedWidget, QVBoxLayout, QWidget)

from .. import bidi, claude_setup
from .controls import Section, Segmented, Select, Stepper, Switch, rtl_buttons
from .glass import GlassDialog
from .widgets import CharacterRow
from ..i18n import I18n
from ..kb import KnowledgeBase
from ..store import ASSETS, History, Profiles, Settings
from . import theme

# MapleStory Classic job tree: base class -> [(job, min level)]
JOBS = {
    "Beginner": [("Beginner", 1)],
    "Warrior": [("Beginner", 1), ("Warrior", 10), ("Fighter", 30), ("Page", 30), ("Spearman", 30),
                ("Crusader", 70), ("White Knight", 70), ("Dragon Knight", 70)],
    "Magician": [("Beginner", 1), ("Magician", 8), ("F/P Wizard", 30), ("I/L Wizard", 30), ("Cleric", 30),
                 ("F/P Mage", 70), ("I/L Mage", 70), ("Priest", 70)],
    "Bowman": [("Beginner", 1), ("Bowman", 10), ("Hunter", 30), ("Crossbowman", 30), ("Ranger", 70), ("Sniper", 70)],
    "Thief": [("Beginner", 1), ("Thief", 10), ("Assassin", 30), ("Bandit", 30), ("Hermit", 70), ("Chief Bandit", 70)],
}
CLASS_HE = {"Beginner": "ביגינר", "Warrior": "לוחם", "Magician": "קוסם", "Bowman": "קשת", "Thief": "גנב"}
MAX_LEVEL = 200


def jobs_for(base_class: str, level: int) -> list[str]:
    return [j for j, lv in JOBS.get(base_class, []) if lv <= level]


def _title(text: str) -> QLabel:
    lb = QLabel(bidi.plain(text), objectName="PageTitle")
    lb.setWordWrap(True)
    return lb


def _body(text: str) -> QLabel:
    lb = QLabel(bidi.plain(text), objectName="PageBody")
    lb.setWordWrap(True)
    return lb


def _field(text: str) -> QLabel:
    return QLabel(text, objectName="FieldLabel")


class _Bridge(QObject):
    status = Signal(str)
    account = Signal(object)
    logged_out = Signal()


class CharacterForm(QWidget):
    """Name, class (cards), level, job. Used by onboarding and 'add character'."""

    changed = Signal()

    def __init__(self, t: I18n, kb: KnowledgeBase):
        super().__init__()
        self.t = t
        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        lay.addWidget(_field(t("ob_char_name")))
        self.name = QLineEdit()
        self.name.setMaxLength(24)
        self.name.textChanged.connect(lambda *_: self.changed.emit())
        lay.addWidget(self.name)

        lay.addWidget(_field(t("ob_class")))
        grid = QGridLayout()
        self.class_group = QButtonGroup(self)
        self.class_group.setExclusive(True)
        for i, cls in enumerate(JOBS):
            b = QPushButton()
            b.setCheckable(True)
            b.setObjectName("Quick")
            b.setMinimumHeight(72)
            img = kb.image_path(f"class/{cls.lower()}")
            label = cls if t.lang == "en" else f"{CLASS_HE[cls]}\n{cls}"
            b.setText(label)
            if img:
                from PySide6.QtGui import QIcon
                b.setIcon(QIcon(str(img)))
                b.setIconSize(QPixmap(str(img)).size().scaled(40, 40, Qt.KeepAspectRatio))
            b.setProperty("cls", cls)
            self.class_group.addButton(b)
            grid.addWidget(b, i // 3, i % 3)
        self.class_group.buttonToggled.connect(lambda *_: (setattr(self, "_job_picked", False), self._refresh_jobs()))
        lay.addLayout(grid)

        row = QHBoxLayout()
        col1 = QVBoxLayout()
        col1.addWidget(_field(t("ob_level")))
        self.level = Stepper(1, MAX_LEVEL, 1)
        self.level.valueChanged.connect(lambda *_: self._refresh_jobs())
        col1.addWidget(self.level)
        row.addLayout(col1)
        col2 = QVBoxLayout()
        col2.addWidget(_field(t("ob_job")))
        self.job = Select()
        self.job.currentIndexChanged.connect(lambda *_: self.changed.emit())
        self._job_picked = False       # the user chose a job by hand: keep it while it stays available
        self.job.picked.connect(lambda *_: setattr(self, "_job_picked", True))
        col2.addWidget(self.job)
        self.job_fixed = QLabel("Beginner", objectName="JobFixed")
        # an English word in a Hebrew form still starts on the right, like the other fields
        self.job_fixed.setAlignment((Qt.AlignRight if t.rtl else Qt.AlignLeft) | Qt.AlignAbsolute | Qt.AlignVCenter)
        self.job_fixed.hide()
        col2.addWidget(self.job_fixed)
        row.addLayout(col2, 1)
        lay.addLayout(row)
        self.job_hint = QLabel(objectName="JobHint")
        self.job_hint.setWordWrap(True)
        lay.addWidget(self.job_hint)
        # the profile keeps itself current from screenshots: say so, so nobody feels they must maintain it
        note = QFrame(objectName="InfoNote")
        note.setLayoutDirection(Qt.RightToLeft if t.rtl else Qt.LeftToRight)
        nl = QHBoxLayout(note)
        nl.setContentsMargins(12, 10, 12, 10)
        nl.setSpacing(10)
        icon = QLabel(theme.ICON["info"], objectName="InfoIcon")
        nl.addWidget(icon, 0, Qt.AlignTop)
        text = QLabel(bidi.plain(t("auto_profile_note"), t.rtl), objectName="InfoText")
        text.setWordWrap(True)
        nl.addWidget(text, 1)
        lay.addSpacing(6)
        lay.addWidget(note)
        lay.addStretch(1)

    def base_class(self) -> str | None:
        b = self.class_group.checkedButton()
        return b.property("cls") if b else None

    def _refresh_jobs(self):
        cls = self.base_class()
        previous = self.job.currentText()
        hint = ""
        jobs = ["Beginner"] if cls == "Beginner" else []
        if cls and cls != "Beginner":
            # a class is chosen at its 1st job, so its level starts there (Warrior 10, Magician 8…)
            first_level = next(lv for j, lv in JOBS[cls] if j != "Beginner")
            self.level.setMinimum(first_level)
            jobs = [j for j in jobs_for(cls, self.level.value()) if j != "Beginner"]
            upcoming = [(j, lv) for j, lv in JOBS[cls] if lv > self.level.value()]
            if upcoming:
                lv = upcoming[0][1]
                names = [job for job, need in upcoming if need == lv]
                hint = (self.t("job_hint_next", job=names[0], level=lv) if len(names) == 1 else
                        self.t("job_hint_next_many", jobs=", ".join(names), level=lv))
        else:
            self.level.setMinimum(1)
        # one possible job → a fixed field; a real choice → a dropdown
        single = len(jobs) <= 1
        self.job.setVisible(bool(cls) and not single)
        self.job_fixed.setVisible(bool(cls) and single)
        self.job_fixed.setText(jobs[0] if jobs else "")
        self.job.clear()
        if not single:
            self.job.addItems(jobs)
            keep = self._job_picked and previous in jobs
            self.job.setCurrentIndex(jobs.index(previous) if keep else len(jobs) - 1)
        self.job_hint.setText(bidi.plain(hint, self.t.rtl) if hint else "")
        self.job_hint.setVisible(bool(hint))
        self.changed.emit()

    def load(self, c) -> None:
        """Pre-fill for editing an existing character."""
        self.name.setText(c.name)
        for b in self.class_group.buttons():
            if b.property("cls") == c.base_class:
                b.setChecked(True)
        self.level.setValue(c.level)
        self._refresh_jobs()
        self.job.setCurrentText(c.job)
        self._job_picked = True        # the saved job is the player's choice

    def current_job(self) -> str:
        return self.job_fixed.text() if self.job_fixed.isVisibleTo(self) else self.job.currentText()

    def valid(self) -> bool:
        return bool(self.name.text().strip()) and bool(self.base_class()) and bool(self.current_job())

    def values(self) -> tuple[str, str, str, int]:
        return self.name.text().strip(), self.base_class(), self.current_job(), self.level.value()


class Onboarding(GlassDialog):
    """Language → Claude connection → character. Every step is required."""

    def __init__(self, settings: Settings, profiles: Profiles, kb: KnowledgeBase, stylesheet_fn, only_character=False,
                 edit_id: str | None = None):
        self.t = I18n(settings["language"] or "he")
        self.edit_id = edit_id
        only_character = only_character or edit_id is not None
        title = self.t("add_character") if only_character else "Maple Helper"
        super().__init__(title, self.t.rtl)
        self.settings, self.profiles, self.kb = settings, profiles, kb
        self.stylesheet_fn = stylesheet_fn
        self.only_character = only_character
        self.resize(600, 680)
        self._bridge = _Bridge()
        self._bridge.status.connect(self._on_status)
        self._claude_ok = False
        self._build()

    def _build(self):
        self.title_label.hide()
        self.setStyleSheet(self.stylesheet_fn(1.0))
        outer = QVBoxLayout(self.content)
        outer.setContentsMargins(10, 4, 10, 0)
        self.stack = QStackedWidget()
        outer.addWidget(self.stack, 1)
        nav = QHBoxLayout()
        self.back = QPushButton(self.t("ob_back"), objectName="Secondary")
        self.next = QPushButton(self.t("ob_next"), objectName="Primary")
        self.back.clicked.connect(self._go_back)
        self.next.clicked.connect(self._go_next)
        nav.addWidget(self.back)
        nav.addStretch(1)
        nav.addWidget(self.next)
        outer.addLayout(nav)

        self.pages = []
        if not self.only_character:
            self.pages.append(self._page_language())
            self.pages.append(self._page_claude())
        self.pages.append(self._page_character())
        if not self.only_character:
            self.pages.append(self._page_done())
        for p in self.pages:
            self.stack.addWidget(p)
        rtl_buttons(self, self.t.rtl)
        self._update_nav()

    # pages ---------------------------------------------------------------

    def _page_language(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        logo = QLabel()
        wm = ASSETS / "brand" / "wordmark.png"
        if wm.exists():
            logo.setPixmap(QPixmap(str(wm)).scaled(260, 260, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        logo.setAlignment(Qt.AlignCenter)
        lay.addWidget(logo)
        for line in ("העוזר האישי שלכם ב-MapleStory Classic", "Your personal MapleStory Classic assistant"):
            lb = _body(line)
            lb.setAlignment(Qt.AlignHCenter)
            lay.addWidget(lb)
        lay.addSpacing(16)
        row = QHBoxLayout()
        self.lang_group = QButtonGroup(self)
        for code, label in (("he", "עברית"), ("en", "English")):
            b = QPushButton(label, objectName="Quick")
            b.setCheckable(True)
            b.setMinimumHeight(56)
            b.setProperty("lang", code)
            if (self.settings["language"] or "he") == code:
                b.setChecked(True)
            self.lang_group.addButton(b)
            row.addWidget(b)
        self.lang_group.buttonClicked.connect(self._on_language)
        lay.addLayout(row)
        lay.addStretch(1)
        return w

    def _page_claude(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(12)
        lay.addWidget(_title(self.t("ob_connect")))
        lay.addWidget(_body(self.t("ob_connect_body") + " " + self.t("ob_need_plan")))
        lay.addSpacing(6)
        rtl = self.t.rtl
        sec = Section(self.t("sec_account"), rtl)
        status_row = QWidget()
        srow = QHBoxLayout(status_row)
        srow.setContentsMargins(0, 6, 0, 6)
        srow.setSpacing(14)
        self.status_label = QLabel(bidi.plain(self.t("ob_checking"), rtl), objectName="RowLabel")
        self.status_label.setWordWrap(True)
        srow.addWidget(self.status_label, 1)
        self.install_btn = QPushButton(self.t("ob_install"), objectName="Link")
        self.login_btn = QPushButton(self.t("ob_login"), objectName="Link")
        self.check_btn = QPushButton(self.t("ob_check"), objectName="Link")
        self.install_btn.clicked.connect(lambda: (claude_setup.install(), self._poll_status(90)))
        self.login_btn.clicked.connect(lambda: (claude_setup.login(), self._poll_status(120)))
        self.check_btn.clicked.connect(self._check_status)
        for b in (self.install_btn, self.login_btn, self.check_btn):
            b.setCursor(Qt.PointingHandCursor)
            srow.addWidget(b)
        self.install_btn.hide()
        self.login_btn.hide()
        sec.add_widget(status_row)
        lay.addWidget(sec)
        lay.addSpacing(8)
        sec = Section(self.t("ob_use_api_key"), rtl)
        kbox = QWidget()
        krow = QHBoxLayout(kbox)
        krow.setContentsMargins(0, 10, 0, 10)
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.Password)
        self.key_edit.setPlaceholderText(self.t("ob_api_key_hint"))
        self.key_edit.setLayoutDirection(Qt.LeftToRight)
        key_btn = QPushButton(self.t("ob_check"), objectName="Secondary")
        key_btn.setCursor(Qt.PointingHandCursor)
        key_btn.clicked.connect(self._check_key)
        krow.addWidget(self.key_edit, 1)
        krow.addWidget(key_btn)
        sec.add_widget(kbox)
        lay.addWidget(sec)
        lay.addStretch(1)
        return w

    def _page_character(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        heading = (self.t("edit_character") if self.edit_id else
                   self.t("add_character") if self.only_character else self.t("ob_welcome"))
        lay.addWidget(_title(heading))
        self.form = CharacterForm(self.t, self.kb)
        if self.edit_id:
            c = next((c for c in self.profiles.characters if c.id == self.edit_id), None)
            if c:
                self.form.load(c)
        self.form.changed.connect(self._update_nav)
        lay.addWidget(self.form, 1)
        return w

    def _page_done(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(14)
        mascot = QLabel()
        m = ASSETS / "brand" / "mascot.png"
        if m.exists():
            mascot.setPixmap(QPixmap(str(m)).scaled(220, 220, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        mascot.setAlignment(Qt.AlignCenter)
        lay.addWidget(mascot)
        title = _title(self.t("ob_done_hint"))
        title.setAlignment(Qt.AlignHCenter)
        lay.addWidget(title)
        lay.addSpacing(4)
        sec = Section("", self.t.rtl)
        sec.add_row(self.t("ob_borderless"))
        sec.add_row(self.t("ob_privacy"))
        lay.addWidget(sec)
        note = QLabel(bidi.plain(self.t("unofficial"), self.t.rtl), objectName="RowHint")
        note.setWordWrap(True)
        note.setAlignment(Qt.AlignHCenter)
        lay.addWidget(note)
        lay.addStretch(1)
        return w

    # logic ---------------------------------------------------------------

    RESTART = 2

    def _on_language(self, btn):
        lang = btn.property("lang")
        if lang != self.t.lang:
            # reopen in the chosen language (the app loops on RESTART)
            self.settings["language"] = lang
            self.done(self.RESTART)
            return
        self.settings["language"] = lang
        self._update_nav()

    def _check_status(self):
        self.status_label.setText(bidi.plain(self.t("ob_checking"), self.t.rtl))
        threading.Thread(target=lambda: self._bridge.status.emit(claude_setup.status()), daemon=True).start()

    def _poll_status(self, seconds: int):
        self._poll_left = seconds // 3
        self._poll_timer = QTimer(self, interval=3000)
        self._poll_timer.timeout.connect(self._poll_tick)
        self._poll_timer.start()

    def _poll_tick(self):
        self._poll_left -= 1
        if self._poll_left <= 0 or self._claude_ok:
            self._poll_timer.stop()
            return
        self._check_status()

    def _on_status(self, st: str):
        self._claude_ok = st == "ok"
        text = {"ok": self.t("ob_connected"), "logged_out": self.t("ob_not_logged"),
                "not_installed": self.t("ob_not_installed")}[st]
        self.status_label.setText(bidi.plain(text, self.t.rtl))
        self.install_btn.setVisible(st == "not_installed")
        self.login_btn.setVisible(st == "logged_out")
        if self._claude_ok:
            self.settings["api_key_fallback"] = False
        self._update_nav()

    def _check_key(self):
        key = self.key_edit.text().strip()
        if key and claude_setup.test_api_key(key):
            claude_setup.save_api_key(key)
            self.settings["api_key_fallback"] = True
            self._claude_ok = True
            self.status_label.setText(bidi.plain(self.t("ob_connected"), self.t.rtl))
        else:
            self.status_label.setText("✗")
        self._update_nav()

    def showEvent(self, e):
        super().showEvent(e)
        if not self.only_character:
            self._check_status()

    def _current_ok(self) -> bool:
        page = self.stack.currentWidget()
        if not self.only_character and page is self.pages[0]:
            return self.lang_group.checkedButton() is not None
        if not self.only_character and page is self.pages[1]:
            return self._claude_ok
        if page.findChild(CharacterForm):
            return self.form.valid()
        return True

    def _update_nav(self):
        i = self.stack.currentIndex()
        self.back.setVisible(i > 0)
        last = i == self.stack.count() - 1
        finish = self.t("save_changes") if self.edit_id else self.t("ob_finish")
        self.next.setText(bidi.plain(finish if last else self.t("ob_next"), self.t.rtl))
        self.next.setEnabled(self._current_ok())

    def _go_back(self):
        self.stack.setCurrentIndex(max(0, self.stack.currentIndex() - 1))
        self._update_nav()

    def _go_next(self):
        if not self._current_ok():
            return
        if self.stack.currentIndex() == self.stack.count() - 1:
            if self.edit_id:
                self.profiles.edit(self.edit_id, *self.form.values())
            else:
                self.profiles.add(*self.form.values())
            if not self.only_character:
                self.settings["onboarding_done"] = True
            self.accept()
            return
        self.stack.setCurrentIndex(self.stack.currentIndex() + 1)
        self._update_nav()

    def restart_on_language(self):
        """After a language restart, open straight on the Claude step."""
        if not self.only_character and self.stack.count() > 1:
            self.stack.setCurrentIndex(1)
            self._update_nav()


class ConfirmDialog(GlassDialog):
    """Glass confirmation for destructive actions only (Apple: use sparingly)."""

    def __init__(self, title: str, body: str, confirm: str, cancel: str, rtl: bool, stylesheet: str, danger=True):
        super().__init__(title, rtl)
        self.setStyleSheet(stylesheet)
        self.resize(420, 230)
        lay = QVBoxLayout(self.content)
        msg = QLabel(bidi.plain(body, rtl), objectName="DialogBody")
        msg.setWordWrap(True)
        lay.addWidget(msg)
        lay.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        no = QPushButton(cancel, objectName="Secondary")
        yes = QPushButton(confirm, objectName="Danger" if danger else "Primary")
        for b in (no, yes):
            b.setCursor(Qt.PointingHandCursor)
        no.clicked.connect(self.reject)
        yes.clicked.connect(self.accept)
        row.addWidget(no)
        row.addWidget(yes)
        lay.addLayout(row)
        rtl_buttons(self, rtl)
        no.setFocus()


class SettingsDialog(GlassDialog):
    changed = Signal()
    update_kb_requested = Signal()
    history_cleared = Signal()
    account_changed = Signal()
    patch_notes_requested = Signal()

    def __init__(self, settings: Settings, profiles: Profiles, kb: KnowledgeBase, stylesheet_fn):
        self.t = t = I18n(settings["language"] or "he")
        super().__init__(t("settings"), t.rtl)
        self.settings, self.profiles, self.kb = settings, profiles, kb
        self.stylesheet_fn = stylesheet_fn
        self.setStyleSheet(stylesheet_fn(1.0))
        self.resize(500, 720)
        rtl = t.rtl

        outer = QVBoxLayout(self.content)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget(objectName="Feed")
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 6, 0)
        lay.setSpacing(18)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        # appearance
        sec = Section(t("sec_appearance"), rtl)
        self.appearance = Segmented([(t("appearance_dark_short"), "dark"), (t("appearance_light_short"), "light")],
                                    settings["appearance"], rtl)
        sec.add_row(t("appearance"), self.appearance)
        self.font = Segmented([("A", 13), ("A", 14), ("A", 16)], settings["font_size"], rtl)
        # small / medium / large "A" (the stylesheet wins over setFont, so size it there)
        for i, b in enumerate(self.font.group.buttons()):
            b.setStyleSheet(f"font-size: {11 + i * 4}px; font-weight: 600;")
        sec.add_row(t("font_size"), self.font)
        self.lang = Segmented([("עברית", "he"), ("English", "en")], settings["language"] or "he", rtl)
        sec.add_row(t("language"), self.lang)
        lay.addWidget(sec)

        # keys
        sec = Section(t("sec_keys"), rtl)
        fkeys = [f"F{i}" for i in range(1, 13)]
        self.hk_toggle = Select()
        self.hk_toggle.addItems(fkeys)
        self.hk_toggle.setCurrentText(settings["hotkey_toggle"])
        sec.add_row(t("hotkey_toggle"), self.hk_toggle)
        self.hk_voice = Select()
        self.hk_voice.addItems(fkeys)
        self.hk_voice.setCurrentText(settings["hotkey_voice"])
        sec.add_row(t("hotkey_voice"), self.hk_voice)
        self.voice_send = Switch(settings["voice_send_immediately"])
        sec.add_row(t("voice_send"), self.voice_send)
        lay.addWidget(sec)

        # answers
        sec = Section(t("sec_answers"), rtl)
        self.length = Segmented([(t("short"), "short"), (t("detailed"), "detailed")], settings["answer_length"], rtl)
        sec.add_row(t("answer_length"), self.length)
        lay.addWidget(sec)

        # privacy & system
        sec = Section(t("sec_system"), rtl)
        self.autostart = Switch(settings["start_with_windows"])
        sec.add_row(t("start_with_windows"), self.autostart)
        lay.addWidget(sec)

        # Claude account
        sec = Section(t("sec_account"), rtl)
        self.account_label = QLabel(bidi.plain(t("ob_checking"), rtl), objectName="RowLabel")
        self.account_label.setWordWrap(True)
        self.account_label.setContentsMargins(0, 10, 0, 10)
        sec.add_widget(self.account_label)
        self.switch_btn = QPushButton(t("account_switch"), objectName="Link")
        self.switch_btn.clicked.connect(self._switch_account)
        sec.add_widget(self.switch_btn)
        self.logout_btn = QPushButton(t("account_logout"), objectName="LinkDanger")
        self.logout_btn.clicked.connect(self._logout)
        sec.add_widget(self.logout_btn)
        for b in (self.switch_btn, self.logout_btn):
            b.setCursor(Qt.PointingHandCursor)
            b.hide()
        lay.addWidget(sec)
        self._account_bridge = _Bridge()
        self._account_bridge.account.connect(self._on_account)
        self._account_bridge.logged_out.connect(self._start_login)
        self._account_status = None
        self._login_timer = QTimer(self, interval=3000)
        self._login_timer.timeout.connect(self._login_tick)
        self._refresh_account()

        # characters
        sec = Section(t("characters"), rtl)
        self.chars_box = QWidget(objectName="Feed")
        self.chars = QVBoxLayout(self.chars_box)
        self.chars.setContentsMargins(0, 0, 0, 0)
        self.chars.setSpacing(0)
        sec.add_widget(self.chars_box)
        self._fill_chars()
        add = QPushButton("＋  " + t("add_character"), objectName="Link")
        add.setCursor(Qt.PointingHandCursor)
        add.clicked.connect(self._add_char)
        sec.add_widget(add)
        lay.addWidget(sec)

        # data
        sec = Section(t("sec_data"), rtl)
        upd = QPushButton(t("update_kb"), objectName="Link")
        upd.setCursor(Qt.PointingHandCursor)
        upd.clicked.connect(self.update_kb_requested.emit)
        sec.add_widget(upd)
        notes = QPushButton(t("patch_notes"), objectName="Link")
        notes.setCursor(Qt.PointingHandCursor)
        notes.clicked.connect(self.patch_notes_requested.emit)
        sec.add_widget(notes)
        clear = QPushButton(t("clear_history"), objectName="LinkDanger")
        clear.setCursor(Qt.PointingHandCursor)
        clear.clicked.connect(self._clear_history)
        sec.add_widget(clear)
        lay.addWidget(sec)

        credit = QLabel("\n".join(bidi.plain(t(k), rtl) for k in ("credits", "unofficial", "disclaimer")),
                        objectName="RowHint")
        credit.setWordWrap(True)
        credit.setAlignment(Qt.AlignHCenter)
        lay.addWidget(credit)
        lay.addStretch(1)

        brow = QHBoxLayout()
        brow.setContentsMargins(0, 10, 0, 0)
        brow.addStretch(1)
        save = QPushButton(t("save"), objectName="Primary")
        save.setCursor(Qt.PointingHandCursor)
        save.setMinimumWidth(180)
        save.clicked.connect(self._save)
        brow.addWidget(save)
        brow.addStretch(1)
        outer.addLayout(brow)
        rtl_buttons(self, rtl)

    # Claude account ------------------------------------------------------

    def _refresh_account(self):
        threading.Thread(target=lambda: self._account_bridge.account.emit(claude_setup.account()),
                         daemon=True).start()

    def _set_account_text(self, text: str):
        self.account_label.setText(bidi.plain(text, self.t.rtl))

    def _on_account(self, acc: dict):
        t = self.t
        st = acc["status"]
        was, self._account_status = self._account_status, st
        api_key = bool(self.settings["api_key_fallback"])
        if api_key:
            self._set_account_text(t("account_api_key"))
        elif st == "ok":
            self._set_account_text(t("account_signed_in", email=acc.get("email") or "Claude"))
        elif not self._login_timer.isActive():
            self._set_account_text(t("ob_not_logged") if st == "logged_out" else t("ob_not_installed"))
        connected = api_key or st == "ok"
        self.switch_btn.setText(t("account_switch") if connected else t("ob_login"))
        self.switch_btn.setVisible(st != "not_installed")
        self.logout_btn.setVisible(connected)
        if self._login_timer.isActive() and st == "ok":
            self._login_timer.stop()
        if was is not None and was != st and not api_key:
            self.account_changed.emit()

    def _switch_account(self):
        """Sign out, then run the official sign-in so another account can be chosen in the browser."""
        self.switch_btn.setEnabled(False)
        self.logout_btn.hide()
        self._set_account_text(self.t("account_signing_out"))
        if self.settings["api_key_fallback"]:
            claude_setup.delete_api_key()
            self.settings["api_key_fallback"] = False
            self.account_changed.emit()

        def work():
            claude_setup.logout()
            self._account_bridge.logged_out.emit()
        threading.Thread(target=work, daemon=True).start()

    def _start_login(self):
        self.switch_btn.setEnabled(True)
        self._account_status = "logged_out"
        self.account_changed.emit()
        claude_setup.login()
        self._set_account_text(self.t("account_browser"))
        self._login_left = 60   # 3 minutes
        self._login_timer.start()

    def _login_tick(self):
        self._login_left -= 1
        if self._login_left <= 0:
            self._login_timer.stop()
        self._refresh_account()

    def _logout(self):
        t = self.t
        dlg = ConfirmDialog(t("account_logout"), t("account_logout_confirm"), t("account_logout"), t("cancel"),
                            t.rtl, self.stylesheet_fn(1.0))
        if not dlg.exec():
            return
        self.logout_btn.hide()
        self._set_account_text(t("account_signing_out"))
        if self.settings["api_key_fallback"]:
            claude_setup.delete_api_key()
            self.settings["api_key_fallback"] = False
            self.account_changed.emit()
            self._refresh_account()
            return

        def work():
            claude_setup.logout()
            self._account_bridge.account.emit(claude_setup.account())
        threading.Thread(target=work, daemon=True).start()

    def _fill_chars(self):
        while self.chars.count():
            w = self.chars.takeAt(0).widget()
            if w:
                w.deleteLater()
        for i, c in enumerate(self.profiles.characters):
            if i:
                sep = QFrame(objectName="Separator")
                sep.setFixedHeight(1)
                self.chars.addWidget(sep)
            row = CharacterRow(c, self.profiles.avatar_path(c), self.kb, c.id == self.profiles.active_id,
                               self.t.rtl, can_delete=True)
            row.chosen.connect(self._choose_char)
            row.edit_requested.connect(self._edit_char)
            row.delete_requested.connect(self._delete_char)
            self.chars.addWidget(row)

    def _choose_char(self, cid: str):
        self.profiles.set_active(cid)
        self._fill_chars()
        self.changed.emit()

    def _edit_char(self, cid: str):
        dlg = Onboarding(self.settings, self.profiles, self.kb, self.stylesheet_fn, edit_id=cid)
        if dlg.exec():
            self._fill_chars()
            self.changed.emit()

    def _delete_char(self, cid: str):
        c = next((c for c in self.profiles.characters if c.id == cid), None)
        if not c:
            return
        t = self.t
        dlg = ConfirmDialog(t("delete_character"), t("delete_character_confirm", name=c.name), t("delete"),
                            t("cancel"), t.rtl, self.stylesheet_fn(1.0))
        if dlg.exec():
            self.profiles.remove(cid)
            if not self.profiles.characters:
                # advice needs a character: offer to create one right away
                Onboarding(self.settings, self.profiles, self.kb, self.stylesheet_fn, only_character=True).exec()
            self._fill_chars()
            self.changed.emit()

    def _add_char(self):
        dlg = Onboarding(self.settings, self.profiles, self.kb, self.stylesheet_fn, only_character=True)
        if dlg.exec():
            self._fill_chars()

    def _clear_history(self):
        c = self.profiles.active
        if not c:
            return
        t = self.t
        dlg = ConfirmDialog(t("clear_history"), t("clear_history_confirm", name=c.name), t("clear"), t("cancel"),
                            t.rtl, self.stylesheet_fn(1.0))
        if dlg.exec():
            History(c.id).clear()
            self.history_cleared.emit()

    def _save(self):
        s = self.settings
        s.data.update({
            "language": self.lang.value(),
            "appearance": self.appearance.value(),
            "font_size": self.font.value(),
            "hotkey_toggle": self.hk_toggle.currentText(),
            "hotkey_voice": self.hk_voice.currentText(),
            "voice_send_immediately": self.voice_send.isChecked(),
            "answer_length": self.length.value(),
            "start_with_windows": self.autostart.isChecked(),
        })
        s.save()
        self.changed.emit()
        self.accept()
