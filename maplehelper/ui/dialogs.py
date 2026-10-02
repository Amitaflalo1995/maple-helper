"""Onboarding (mandatory, no skipping), character editor and settings."""
from __future__ import annotations

import sys
import threading

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QButtonGroup, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QScrollArea, QStackedWidget, QVBoxLayout, QWidget)

from .. import bidi, providers
from ..providers.base import login_failed, stop_login
from .controls import Section, Segmented, Select, Stepper, Switch, rtl_buttons
from .glass import GlassDialog
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
    status = Signal(str, str)      # provider, status
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
    """Language → AI connection (Claude or Codex) → character. Every step is required."""

    report_requested = Signal()     # "Report a problem" on the connect page, before Settings exist

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
        self.provider = providers.get(settings["provider"]).name
        self._ai_ok = False
        self._signing_in = False   # a sign-in/install is under way: keep the hint, re-check quietly
        self.finished.connect(lambda *_: stop_login())
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
            self.pages.append(self._page_ai())
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

    def _page_ai(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(12)
        lay.addWidget(_title(self.t("ob_connect")))
        rtl = self.t.rtl
        self.provider_pick = Segmented([(p.label, p.name) for p in providers.PROVIDERS.values()], self.provider, rtl)
        self.provider_pick.changed.connect(self._on_provider)
        prow = QHBoxLayout()
        prow.addWidget(self.provider_pick)
        prow.addStretch(1)
        lay.addLayout(prow)
        self.ai_body = _body("")
        lay.addWidget(self.ai_body)
        lay.addSpacing(6)
        sec = self.account_sec = Section(self.t("sec_account"), rtl)
        status_row = QWidget()
        srow = QHBoxLayout(status_row)
        srow.setContentsMargins(0, 6, 0, 6)
        srow.setSpacing(14)
        self.status_label = QLabel(bidi.plain(self.t("ob_checking"), rtl), objectName="RowLabel")
        self.status_label.setWordWrap(True)
        srow.addWidget(self.status_label, 1)
        self.install_btn = QPushButton(objectName="Link")
        self.login_btn = QPushButton(objectName="Link")
        self.check_btn = QPushButton(self.t("ob_check"), objectName="Link")
        self.install_btn.clicked.connect(self._start_install)
        self.login_btn.clicked.connect(self._start_login)
        self.check_btn.clicked.connect(self._check_status)
        for b in (self.install_btn, self.login_btn, self.check_btn):
            b.setCursor(Qt.PointingHandCursor)
            srow.addWidget(b)
        self.install_btn.hide()
        self.login_btn.hide()
        sec.add_widget(status_row)
        self.login_hint = QLabel(objectName="RowHint")
        self.login_hint.setWordWrap(True)
        self.login_hint.hide()
        sec.add_widget(self.login_hint)
        lay.addWidget(sec)
        lay.addSpacing(8)
        sec = Section(self.t("ob_use_api_key"), rtl)
        kbox = QWidget()
        krow = QHBoxLayout(kbox)
        krow.setContentsMargins(0, 10, 0, 10)
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.Password)
        self.key_edit.setLayoutDirection(Qt.LeftToRight)
        key_btn = QPushButton(self.t("ob_check"), objectName="Secondary")
        key_btn.setCursor(Qt.PointingHandCursor)
        key_btn.clicked.connect(self._check_key)
        krow.addWidget(self.key_edit, 1)
        krow.addWidget(key_btn)
        sec.add_widget(kbox)
        lay.addWidget(sec)
        lay.addStretch(1)
        report_btn = QPushButton(self.t("report_problem"), objectName="Link")
        report_btn.setCursor(Qt.PointingHandCursor)
        report_btn.clicked.connect(self.report_requested.emit)
        lay.addWidget(report_btn, 0, Qt.AlignHCenter)
        self._label_ai_page()
        return w

    def _ai(self):
        return providers.get(self.provider)

    def _label_ai_page(self):
        """Texts of the connect page for the chosen provider."""
        t, p = self.t, self.provider
        self.ai_body.setText(bidi.plain(t.p("ob_connect_body", p) + " " + t.p("ob_need_plan", p), t.rtl))
        self.account_sec.set_header(t.p("sec_account", p))
        self.install_btn.setText(t.p("ob_install", p))
        self.login_btn.setText(t.p("ob_login", p))
        self.key_edit.clear()
        self.key_edit.setPlaceholderText(t.p("ob_api_key_hint", p))
        if getattr(self, "privacy_label", None):          # the done page is built after this one
            self.privacy_label.setText(bidi.plain(t.p("ob_privacy", p), t.rtl))

    def _on_provider(self, name: str):
        self.provider = self.settings["provider"] = name
        self._ai_ok = False
        self._end_sign_in()
        self.install_btn.hide()
        self.login_btn.hide()
        self._label_ai_page()
        self._check_status()
        self._update_nav()

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
        self.privacy_label = sec.add_row(self.t.p("ob_privacy", self.provider)).findChild(QLabel, "RowLabel")
        sec.add_row(self.t("disclaimer"))
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

    def _start_login(self):
        self._begin_sign_in()
        self._login_proc = self._ai().login()
        if self._login_proc is None:
            # the sign-in couldn't even start: say so, and offer the official installer instead
            self._end_sign_in()
            self.login_hint.setText(bidi.plain(self.t.p("ob_login_failed", self.provider), self.t.rtl))
            self.login_hint.show()
            self.install_btn.show()
            return
        self.login_hint.setText(bidi.plain(self.t.p("ob_login_wait", self.provider), self.t.rtl))
        self.login_hint.show()
        self.install_btn.show()     # the way out when no sign-in window shows up
        self._poll_status(180)

    def _start_install(self):
        self._begin_sign_in()
        self._ai().install()
        self.login_hint.setText(bidi.plain(self.t("ob_install_wait"), self.t.rtl))
        self.login_hint.show()
        self._poll_status(240)

    def _begin_sign_in(self):
        """The sign-in console, the installer and the browser open as normal windows: stop staying on top
        so they don't hide behind this one (where a click on "Sign in" looked like it did nothing)."""
        self._signing_in = True
        if self.windowFlags() & Qt.WindowStaysOnTopHint:
            self.setWindowFlag(Qt.WindowStaysOnTopHint, False)
            self.show()                                          # (changing a flag hides the window)

    def _end_sign_in(self):
        self._signing_in = False
        if hasattr(self, "_poll_timer"):
            self._poll_timer.stop()
        if not self.windowFlags() & Qt.WindowStaysOnTopHint:
            self.setWindowFlag(Qt.WindowStaysOnTopHint, True)   # (changing a flag hides the window)
            self.show()
            self.raise_()
            self.activateWindow()

    def _check_status(self):
        if not self._signing_in:
            self.status_label.setText(bidi.plain(self.t("ob_checking"), self.t.rtl))
        ai = self._ai()
        threading.Thread(target=lambda: self._bridge.status.emit(ai.name, ai.status()), daemon=True).start()

    def _poll_status(self, seconds: int):
        self._poll_left = seconds // 3
        self._poll_timer = QTimer(self, interval=3000)
        self._poll_timer.timeout.connect(self._poll_tick)
        self._poll_timer.start()

    def _poll_tick(self):
        self._poll_left -= 1
        if self._poll_left <= 0 or self._ai_ok:
            self._poll_timer.stop()
            self._signing_in = False
            return
        if login_failed(getattr(self, "_login_proc", None)):
            self._login_proc = None
            self._end_sign_in()
            self.login_hint.setText(bidi.plain(self.t.p("ob_login_failed", self.provider), self.t.rtl))
            self.install_btn.show()
            return
        self._check_status()

    def _on_status(self, provider: str, st: str):
        if provider != self.provider:
            return            # a check that started before the player switched provider
        t = self.t
        self._ai_ok = st == "ok"
        text = {"ok": t("ob_connected"), "logged_out": t.p("ob_not_logged", provider),
                "not_installed": t.p("ob_not_installed", provider)}[st]
        self.status_label.setText(bidi.plain(text, t.rtl))
        self.login_btn.setVisible(st == "logged_out")
        if self._ai_ok:
            if self._signing_in:
                self._end_sign_in()      # back on top, showing "Connected"
            self.login_hint.hide()
            self.install_btn.hide()
            self.settings.set_api_key_mode(provider, False)
        elif not self._signing_in:
            self.install_btn.setVisible(st == "not_installed")
        self._update_nav()

    def _check_key(self):
        key = self.key_edit.text().strip()
        ai = self._ai()
        if key and ai.test_api_key(key):
            ai.save_api_key(key)
            self.settings.set_api_key_mode(ai.name, True)
            self._ai_ok = True
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
            return self._ai_ok
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
        """After a language restart, open straight on the AI step."""
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
    report_requested = Signal()
    account_changed = Signal()
    patch_notes_requested = Signal()
    whats_new_requested = Signal()

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
        self.instant = Switch(settings["instant_answers"])
        sec.add_row(t("instant_answers"), self.instant, hint=t.p("instant_answers_hint", settings["provider"]))
        lay.addWidget(sec)

        # AI account: the provider and its sign-in act right away (like sign-out), not on Save
        sec = Section(t("sec_ai"), rtl)
        self.provider_pick = Segmented([(p.label, p.name) for p in providers.PROVIDERS.values()],
                                       providers.get(settings["provider"]).name, rtl)
        self.provider_pick.changed.connect(self._on_provider)
        sec.add_row(t("ai_provider"), self.provider_pick)
        # the model acts right away too; under it, which model answered last
        self.model_pick = Select()
        self.model_hint = sec.add_row(t("ai_model"), self.model_pick, hint=" ").findChild(QLabel, "RowHint")
        self.model_hint.setWordWrap(True)
        self.model_pick.picked.connect(self._on_model)
        self._model_values: list = []
        self._models_bridge = _Bridge()
        self._models_bridge.account.connect(lambda r: self._show_models(r["provider"], r["models"]))
        self._fill_models()
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
        self._login_proc = None
        self.finished.connect(lambda *_: stop_login())
        self._login_timer = QTimer(self, interval=3000)
        self._login_timer.timeout.connect(self._login_tick)
        self._refresh_account()

        # usage of the plan above (Claude reports it with each answer, ChatGPT when asked) and saver mode
        sec = self.usage_sec = Section(t("sec_usage"), rtl)
        self.usage_meter = QLabel(objectName="RowLabel")
        self.usage_meter.setWordWrap(True)
        self.usage_meter.setContentsMargins(0, 10, 0, 2)
        sec.add_widget(self.usage_meter)
        self.usage_note = QLabel(objectName="RowHint")
        self.usage_note.setContentsMargins(0, 0, 0, 8)
        sec.add_widget(self.usage_note)
        self.saver = Switch(settings["saver_mode"])
        self.saver_hint = sec.add_row(t("saver_mode"), self.saver, hint=t("saver_hint")).findChild(QLabel, "RowHint")
        lay.addWidget(sec)
        self._limits_bridge = _Bridge()
        self._limits_bridge.account.connect(self._on_limits)
        self._label_usage()

        # privacy & system
        sec = Section(t("sec_system"), rtl)
        self.autostart = Switch(settings["start_with_windows"])
        sec.add_row(t("start_at_login" if sys.platform == "darwin" else "start_with_windows"), self.autostart)
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
        news = QPushButton(t("whats_new"), objectName="Link")
        news.setCursor(Qt.PointingHandCursor)
        news.clicked.connect(self.whats_new_requested.emit)
        sec.add_widget(news)
        report_btn = QPushButton(t("report_problem"), objectName="Link")
        report_btn.setCursor(Qt.PointingHandCursor)
        report_btn.clicked.connect(self.report_requested.emit)
        sec.add_widget(report_btn)
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

    # AI account ----------------------------------------------------------

    def _ai(self):
        return providers.get(self.settings["provider"])

    def _label_usage(self):
        """The meter shows the plan of the AI that answers now (Claude's or ChatGPT's); saver mode is there for both."""
        t, ai = self.t, self._ai()
        self.usage_sec.set_header(t.p("sec_usage", ai.name) if ai.reports_usage else t("sec_saver"))
        self._show_usage(ai.name)
        self.usage_meter.setVisible(ai.reports_usage)
        self.usage_note.setText(bidi.plain(t.p("usage_note", ai.name), t.rtl))
        self.usage_note.setVisible(ai.reports_usage)
        self.saver_hint.setText(bidi.plain(t.p("saver_hint", ai.name), t.rtl))
        if ai.reports_usage and not self.settings.api_key_mode(ai.name):
            threading.Thread(target=lambda: self._limits_bridge.account.emit(
                {"provider": ai.name, "limits": ai.read_limits()}), daemon=True).start()

    def _show_usage(self, provider: str):
        from .. import usage
        self.usage_meter.setText(bidi.plain("\n".join(usage.lines(self.settings, self.t, provider=provider)), self.t.rtl))

    def _on_limits(self, r: dict):
        """Fresh usage read in the background (ChatGPT); ignored if the player switched AI meanwhile."""
        from .. import usage
        if r["provider"] != self._ai().name or not r["limits"]:
            return
        usage.record(self.settings, r["limits"], provider=r["provider"])
        self._show_usage(r["provider"])

    # model ---------------------------------------------------------------

    def _fill_models(self):
        """Claude's list is fixed; ChatGPT's comes from OpenAI, so it fills in a moment later."""
        ai = self._ai()
        if ai.name == "codex":
            self._show_models(ai.name, [(None, "")])
            threading.Thread(target=lambda: self._models_bridge.account.emit(
                {"provider": ai.name, "models": ai.models()}), daemon=True).start()
        else:
            self._show_models(ai.name, ai.models())

    def _show_models(self, name: str, models: list):
        from ..providers.base import model_name
        ai = self._ai()
        if name != ai.name:
            return              # a list that arrived after the player switched AI
        t = self.t
        cur = self.settings[ai.model_setting]
        labels, values = [], []
        for value, shown in models:
            if value is None:
                labels.append(t("model_default", name=shown) if shown else t("model_default_unknown"))
            elif name == "claude" and value == "sonnet":
                labels.append(t("model_recommended", name=shown))
            else:
                labels.append(shown)
            values.append(value)
        if cur not in values:            # a model the list doesn't offer (any more): keep showing it
            labels.append(model_name(cur) if cur else t("model_default_unknown"))
            values.append(cur)
        self._model_values = values
        self.model_pick.clear()
        self.model_pick.addItems(labels)
        self.model_pick.setCurrentIndex(values.index(cur))
        self._model_note()

    def _model_note(self):
        from ..providers.base import model_name
        t, ai = self.t, self._ai()
        lines = [t.p("model_hint", ai.name)]
        last = (self.settings["last_model"] or {}).get(ai.name)
        if last:
            lines.append(t("model_last", name=model_name(last)))
        if self.settings["saver_mode"] and ai.saver_model:
            lines.append(t("model_saver_note", name=ai.saver_model.capitalize()))
        self.model_hint.setText(bidi.plain(" · ".join(lines[:1]) + ("\n" + " · ".join(lines[1:]) if lines[1:] else ""),
                                           t.rtl))

    def _on_model(self, i: int):
        ai = self._ai()
        if 0 <= i < len(self._model_values):
            self.settings[ai.model_setting] = self._model_values[i]
            self.account_changed.emit()      # the app moves its AI to the new model

    def _on_provider(self, name: str):
        self.settings["provider"] = name
        self._fill_models()
        self._label_usage()
        self._login_timer.stop()
        self._account_status = None
        self.switch_btn.hide()
        self.logout_btn.hide()
        self._set_account_text(self.t("ob_checking"))
        self.account_changed.emit()        # the app moves its AI over to this provider
        self._refresh_account()

    def _refresh_account(self):
        ai = self._ai()
        threading.Thread(target=lambda: self._account_bridge.account.emit({**ai.account(), "provider": ai.name}),
                         daemon=True).start()

    def _set_account_text(self, text: str):
        self.account_label.setText(bidi.plain(text, self.t.rtl))

    def _on_account(self, acc: dict):
        t, p = self.t, acc.get("provider")
        if p != self._ai().name:
            return            # a check that started before the player switched provider
        st = acc["status"]
        was, self._account_status = self._account_status, st
        api_key = self.settings.api_key_mode(p) or acc.get("method") == "api_key"
        if api_key:
            self._set_account_text(t("account_api_key"))
        elif st == "ok":
            self._set_account_text(t("account_signed_in", email=acc["email"]) if acc.get("email")
                                   else t("account_signed_in_no_email", name=self._ai().label))
        elif not self._login_timer.isActive():
            self._set_account_text(t.p("ob_not_logged", p) if st == "logged_out" else t.p("ob_not_installed", p))
        connected = api_key or st == "ok"
        self.switch_btn.setText(t("account_switch") if connected else t.p("ob_login", p))
        self.switch_btn.setVisible(st != "not_installed")
        self.logout_btn.setVisible(connected)
        if self._login_timer.isActive() and st == "ok":
            self._login_timer.stop()
            self._set_on_top(True)
        if was is not None and was != st and not api_key:
            self.account_changed.emit()

    def _drop_api_key(self) -> bool:
        """Forget this provider's stored API key; True if it was in use."""
        ai = self._ai()
        if not self.settings.api_key_mode(ai.name):
            return False
        ai.delete_api_key()
        self.settings.set_api_key_mode(ai.name, False)
        self.account_changed.emit()
        return True

    def _switch_account(self):
        """Sign out, then run the official sign-in so another account can be chosen in the browser."""
        self.switch_btn.setEnabled(False)
        self.logout_btn.hide()
        self._set_account_text(self.t("account_signing_out"))
        self._drop_api_key()
        ai = self._ai()

        def work():
            ai.logout()
            self._account_bridge.logged_out.emit()
        threading.Thread(target=work, daemon=True).start()

    def _start_login(self):
        self.switch_btn.setEnabled(True)
        self._account_status = "logged_out"
        self.account_changed.emit()
        self._login_proc = self._ai().login()
        if self._login_proc is None:
            self._set_account_text(self.t.p("ob_login_failed", self._ai().name))
            return
        self._set_on_top(False)   # the sign-in window and the browser must not open behind this one
        self._set_account_text(self.t("account_browser"))
        self._login_left = 60   # 3 minutes
        self._login_timer.start()

    def _set_on_top(self, on: bool):
        if bool(self.windowFlags() & Qt.WindowStaysOnTopHint) != on:
            self.setWindowFlag(Qt.WindowStaysOnTopHint, on)
            self.show()                                          # (changing a flag hides the window)
            if on:
                self.raise_()

    def _login_tick(self):
        self._login_left -= 1
        if login_failed(self._login_proc):
            self._login_left = 0
            self._set_account_text(self.t.p("ob_login_failed", self._ai().name))
        if self._login_left <= 0:
            self._login_timer.stop()
            self._set_on_top(True)
            return
        self._refresh_account()

    def _logout(self):
        t = self.t
        ai = self._ai()
        dlg = ConfirmDialog(t("account_logout"), t.p("account_logout_confirm", ai.name), t("account_logout"),
                            t("cancel"), t.rtl, self.stylesheet_fn(1.0))
        if not dlg.exec():
            return
        self.logout_btn.hide()
        self._set_account_text(t("account_signing_out"))
        if self._drop_api_key():
            self._refresh_account()
            return

        def work():
            ai.logout()
            self._account_bridge.account.emit({**ai.account(), "provider": ai.name})
        threading.Thread(target=work, daemon=True).start()

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
            "instant_answers": self.instant.isChecked(),
            "saver_mode": self.saver.isChecked(),
            "answer_length": self.length.value(),
            "start_with_windows": self.autostart.isChecked(),
        })
        s.save()
        self.changed.emit()
        self.accept()
