"""Onboarding (mandatory, no skipping), character editor and settings."""
from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QPushButton, QScrollArea, QSlider, QSpinBox,
                               QStackedWidget, QVBoxLayout, QWidget)

from .. import bidi, claude_setup
from .controls import Section, Segmented, Switch
from .glass import GlassDialog
from ..i18n import I18n
from ..kb import KnowledgeBase
from ..store import ASSETS, History, Profiles, Settings

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
    lb = QLabel(bidi.plain(text))
    lb.setStyleSheet("font-size: 22px; font-weight: 600;")
    lb.setWordWrap(True)
    return lb


def _body(text: str) -> QLabel:
    lb = QLabel(bidi.plain(text))
    lb.setWordWrap(True)
    lb.setStyleSheet("color: #C9B8A4;")
    return lb


class _Bridge(QObject):
    status = Signal(str)


class CharacterForm(QWidget):
    """Name, class (cards), level, job. Used by onboarding and 'add character'."""

    changed = Signal()

    def __init__(self, t: I18n, kb: KnowledgeBase):
        super().__init__()
        self.t = t
        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        lay.addWidget(QLabel(t("ob_char_name")))
        self.name = QLineEdit()
        self.name.setMaxLength(24)
        self.name.textChanged.connect(lambda *_: self.changed.emit())
        lay.addWidget(self.name)

        lay.addWidget(QLabel(t("ob_class")))
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
        self.class_group.buttonToggled.connect(lambda *_: self._refresh_jobs())
        lay.addLayout(grid)

        row = QHBoxLayout()
        col1 = QVBoxLayout()
        col1.addWidget(QLabel(t("ob_level")))
        self.level = QSpinBox()
        self.level.setRange(1, MAX_LEVEL)
        self.level.setValue(1)
        self.level.valueChanged.connect(lambda *_: self._refresh_jobs())
        col1.addWidget(self.level)
        row.addLayout(col1)
        col2 = QVBoxLayout()
        col2.addWidget(QLabel(t("ob_job")))
        self.job = QComboBox()
        self.job.currentIndexChanged.connect(lambda *_: self.changed.emit())
        col2.addWidget(self.job)
        row.addLayout(col2, 1)
        lay.addLayout(row)
        lay.addStretch(1)

    def base_class(self) -> str | None:
        b = self.class_group.checkedButton()
        return b.property("cls") if b else None

    def _refresh_jobs(self):
        cls = self.base_class()
        self.job.clear()
        if cls:
            jobs = jobs_for(cls, self.level.value())
            self.job.addItems(jobs)
            self.job.setCurrentIndex(len(jobs) - 1)
        self.changed.emit()

    def valid(self) -> bool:
        return bool(self.name.text().strip()) and bool(self.base_class()) and bool(self.job.currentText())

    def values(self) -> tuple[str, str, str, int]:
        return self.name.text().strip(), self.base_class(), self.job.currentText(), self.level.value()


class Onboarding(GlassDialog):
    """Language → Claude connection → character. Every step is required."""

    def __init__(self, settings: Settings, profiles: Profiles, kb: KnowledgeBase, stylesheet_fn, only_character=False):
        self.t = I18n(settings["language"] or "he")
        title = self.t("add_character") if only_character else "Maple Helper"
        super().__init__(title, self.t.rtl, settings["show_in_captures"], strength=settings["glass_strength"])
        self.settings, self.profiles, self.kb = settings, profiles, kb
        self.stylesheet_fn = stylesheet_fn
        self.only_character = only_character
        self.resize(600, 680)
        self._bridge = _Bridge()
        self._bridge.status.connect(self._on_status)
        self._claude_ok = False
        self._build()

    def _build(self):
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
        lay.addWidget(_title("Maple Helper"), 0, Qt.AlignHCenter)
        for line in ("העוזר האישי שלכם ב-MapleStory", "Your personal MapleStory assistant"):
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
        lay.addWidget(_body(self.t("ob_connect_body")))
        lay.addWidget(_body(self.t("ob_need_plan")))
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("font-weight: 600;")
        lay.addWidget(self.status_label)
        row = QHBoxLayout()
        self.install_btn = QPushButton(self.t("ob_install"), objectName="Primary")
        self.login_btn = QPushButton(self.t("ob_login"), objectName="Primary")
        self.check_btn = QPushButton(self.t("ob_check"), objectName="Secondary")
        self.install_btn.clicked.connect(lambda: (claude_setup.install(), self._poll_status(90)))
        self.login_btn.clicked.connect(lambda: (claude_setup.login(), self._poll_status(120)))
        self.check_btn.clicked.connect(self._check_status)
        for b in (self.install_btn, self.login_btn, self.check_btn):
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addSpacing(18)
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color: rgba(255,255,255,0.15);")
        lay.addWidget(line)
        lay.addWidget(_body(self.t("ob_use_api_key")))
        krow = QHBoxLayout()
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.Password)
        self.key_edit.setPlaceholderText(self.t("ob_api_key_hint"))
        self.key_edit.setLayoutDirection(Qt.LeftToRight)
        key_btn = QPushButton(self.t("ob_check"), objectName="Secondary")
        key_btn.clicked.connect(self._check_key)
        krow.addWidget(self.key_edit, 1)
        krow.addWidget(key_btn)
        lay.addLayout(krow)
        lay.addStretch(1)
        return w

    def _page_character(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(_title(self.t("add_character") if self.only_character else self.t("ob_welcome")))
        self.form = CharacterForm(self.t, self.kb)
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
        lay.addWidget(_title(self.t("ob_done_hint")))
        lay.addWidget(_body(self.t("ob_borderless")))
        lay.addWidget(_body(self.t("ob_privacy")))
        lay.addWidget(_body(self.t("unofficial")))
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
        self.status_label.setText(self.t("ob_checking"))
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
        self.status_label.setText(text)
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
            self.status_label.setText(self.t("ob_connected"))
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
        self.next.setText(self.t("ob_finish") if last else self.t("ob_next"))
        self.next.setEnabled(self._current_ok())

    def _go_back(self):
        self.stack.setCurrentIndex(max(0, self.stack.currentIndex() - 1))
        self._update_nav()

    def _go_next(self):
        if not self._current_ok():
            return
        if self.stack.currentIndex() == self.stack.count() - 1:
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


class SettingsDialog(GlassDialog):
    changed = Signal()
    update_kb_requested = Signal()

    def __init__(self, settings: Settings, profiles: Profiles, kb: KnowledgeBase, stylesheet_fn):
        self.t = t = I18n(settings["language"] or "he")
        super().__init__(t("settings"), t.rtl, settings["show_in_captures"], strength=settings["glass_strength"])
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
        self.strength = QSlider(Qt.Horizontal)
        self.strength.setRange(40, 100)
        self.strength.setValue(int(settings["glass_strength"] * 100))
        self.strength.setFixedWidth(160)
        sec.add_row(t("glass_strength"), self.strength, t("glass_strength_hint"))
        self.font = Segmented([("A", 13), ("A", 14), ("A", 16)], settings["font_size"], rtl)
        for i, b in enumerate(self.font.group.buttons()):
            f = b.font()
            f.setPixelSize(11 + i * 2)
            b.setFont(f)
        sec.add_row(t("font_size"), self.font)
        self.lang = Segmented([("עברית", "he"), ("English", "en")], settings["language"] or "he", rtl)
        sec.add_row(t("language"), self.lang)
        lay.addWidget(sec)

        # keys
        sec = Section(t("sec_keys"), rtl)
        fkeys = [f"F{i}" for i in range(1, 13)]
        self.hk_toggle = QComboBox()
        self.hk_toggle.addItems(fkeys)
        self.hk_toggle.setCurrentText(settings["hotkey_toggle"])
        sec.add_row(t("hotkey_toggle"), self.hk_toggle)
        self.hk_voice = QComboBox()
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
        self.show_in_captures = Switch(settings["show_in_captures"])
        sec.add_row(t("show_in_captures"), self.show_in_captures, t("show_in_captures_hint"))
        self.autostart = Switch(settings["start_with_windows"])
        sec.add_row(t("start_with_windows"), self.autostart)
        lay.addWidget(sec)

        # characters
        sec = Section(t("characters"), rtl)
        self.chars = QListWidget()
        self._fill_chars()
        self.chars.itemClicked.connect(lambda it: (self.profiles.set_active(it.data(Qt.UserRole)), self._fill_chars()))
        sec.add_widget(self.chars)
        add = QPushButton(t("add_character"), objectName="Link")
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
        clear = QPushButton(t("clear_history"), objectName="LinkDanger")
        clear.setCursor(Qt.PointingHandCursor)
        clear.clicked.connect(self._clear_history)
        sec.add_widget(clear)
        lay.addWidget(sec)

        credit = QLabel(bidi.plain(t("credits"), rtl) + "\n" + bidi.plain(t("unofficial"), rtl), objectName="RowHint")
        credit.setWordWrap(True)
        credit.setAlignment(Qt.AlignHCenter)
        lay.addWidget(credit)
        lay.addStretch(1)

        brow = QHBoxLayout()
        brow.setContentsMargins(0, 10, 0, 0)
        brow.addStretch(1)
        save = QPushButton(t("save"), objectName="Primary")
        save.setCursor(Qt.PointingHandCursor)
        save.clicked.connect(self._save)
        brow.addWidget(save)
        outer.addLayout(brow)

    def _fill_chars(self):
        self.chars.clear()
        for c in self.profiles.characters:
            mark = "✓  " if c.id == self.profiles.active_id else "     "
            it = QListWidgetItem(bidi.plain(f"{mark}{c.name} · {self.t('level')} {c.level} · {c.job}", self.t.rtl))
            it.setData(Qt.UserRole, c.id)
            self.chars.addItem(it)
        self.chars.setFixedHeight(max(44, 40 * min(4, len(self.profiles.characters))))

    def _add_char(self):
        dlg = Onboarding(self.settings, self.profiles, self.kb, self.stylesheet_fn, only_character=True)
        if dlg.exec():
            self._fill_chars()

    def _clear_history(self):
        c = self.profiles.active
        if c:
            History(c.id).clear()

    def _save(self):
        s = self.settings
        s.data.update({
            "language": self.lang.value(),
            "appearance": self.appearance.value(),
            "glass_strength": self.strength.value() / 100,
            "font_size": self.font.value(),
            "hotkey_toggle": self.hk_toggle.currentText(),
            "hotkey_voice": self.hk_voice.currentText(),
            "voice_send_immediately": self.voice_send.isChecked(),
            "answer_length": self.length.value(),
            "show_in_captures": self.show_in_captures.isChecked(),
            "start_with_windows": self.autostart.isChecked(),
        })
        s.save()
        self.changed.emit()
        self.accept()
