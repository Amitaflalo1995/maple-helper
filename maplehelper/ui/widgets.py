"""Chat building blocks: message bubbles, entity cards, system lines."""
from __future__ import annotations

import webbrowser

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from .. import bidi
from ..kb import KnowledgeBase


def _label(text: str = "", name: str | None = None, rich: bool = False, wrap: bool = True) -> QLabel:
    lb = QLabel()
    if name:
        lb.setObjectName(name)
    lb.setTextFormat(Qt.RichText if rich else Qt.PlainText)
    lb.setWordWrap(wrap)
    lb.setTextInteractionFlags(Qt.TextSelectableByMouse)
    lb.setText(text)
    return lb


class Bubble(QFrame):
    """A chat message. Direction is decided per paragraph, not by the UI language."""

    def __init__(self, text: str, role: str, ui_rtl: bool, tag: str = ""):  # tag: "Mano, Blue Snail"
        super().__init__()
        self.role = role
        self.setObjectName("BubbleUser" if role == "user" else "BubbleBot")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(13, 8, 13, 9)
        if tag:
            t = QLabel("↩ " + tag, objectName="BubbleTag")
            lay.addWidget(t)
        self.label = _label(rich=True)
        self.label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        lay.addWidget(self.label)
        self.set_text(text)

    def set_text(self, text: str) -> None:
        self.label.setText(bidi.to_html(text) if text else "")


class BubbleRow(QWidget):
    """iMessage convention: your messages sit on the trailing side (left in Hebrew), answers span the width."""

    def __init__(self, bubble: Bubble, ui_rtl: bool):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        # the layout mirrors in an RTL UI, so "trailing" is the left edge there
        if bubble.role == "user":
            lay.addSpacing(48)
            lay.addStretch(1)
            lay.addWidget(bubble, 0)
        else:
            lay.addWidget(bubble, 1)


class SystemLine(QLabel):
    def __init__(self, text: str):
        super().__init__(bidi.plain(text))
        self.setObjectName("SystemLine")
        self.setWordWrap(True)
        self.setAlignment(Qt.AlignHCenter)


class NoticeCard(QFrame):
    """An orange note in the conversation with one action (e.g. "what changed?")."""

    clicked = Signal()

    def __init__(self, text: str, action: str, rtl: bool):
        super().__init__(objectName="InfoNote")
        from . import theme
        self.setLayoutDirection(Qt.RightToLeft if rtl else Qt.LeftToRight)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(10)
        lay.addWidget(QLabel(theme.ICON["info"], objectName="InfoIcon"), 0, Qt.AlignVCenter)
        msg = QLabel(bidi.plain(text, rtl), objectName="InfoText")
        msg.setWordWrap(True)
        lay.addWidget(msg, 1)
        btn = QPushButton(bidi.plain(action, rtl), objectName="Link")
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(self.clicked.emit)
        lay.addWidget(btn, 0, Qt.AlignVCenter)


class SessionCard(QFrame):
    """'Last session': levels gained, quests done, questions asked, per character."""

    def __init__(self, title: str, lines: list[str], rtl: bool):
        super().__init__(objectName="Card")
        self.setLayoutDirection(Qt.RightToLeft if rtl else Qt.LeftToRight)
        col = QVBoxLayout(self)
        col.setContentsMargins(14, 10, 14, 10)
        col.setSpacing(3)
        align = (Qt.AlignRight if rtl else Qt.AlignLeft) | Qt.AlignAbsolute
        head = QLabel(bidi.plain(title, rtl), objectName="CardName")
        head.setAlignment(align)
        col.addWidget(head)
        for ln in lines:
            lb = QLabel(bidi.plain(ln, rtl), objectName="CardStat")
            lb.setWordWrap(True)
            lb.setAlignment(align)
            col.addWidget(lb)


# ------------------------------------------------------------------ entity cards

CARD_FIELDS = {
    "monster": [("Level", "level"), ("HP", "HP"), ("EXP", "EXP")],
    "item": [("Level", "level"), ("Attack", "ATT"), ("Defense", "DEF")],
}
FIELD_LABELS_HE = {"level": "לבל", "HP": "HP", "EXP": "EXP", "ATT": "ATT", "DEF": "DEF"}
CATEGORY_LABELS = {
    "monster": ("מפלצת", "Monster"), "item": ("פריט", "Item"), "map": ("מפה", "Map"),
    "npc": ("NPC", "NPC"), "quest": ("קווסט", "Quest"), "skill": ("סקיל", "Skill"),
    "class": ("קלאס", "Class"), "guide": ("מדריך", "Guide"), "shop": ("חנות", "Shop"),
    "crafting": ("Crafting", "Crafting"), "formula": ("נוסחה", "Formula"),
}


class _Selection(QObject):
    """One selected entity for the whole chat. Cards emit `picked`; the overlay decides and broadcasts `changed`."""

    picked = Signal(str)
    changed = Signal(list)    # the tagged keys (empty list = none)


SELECTION = _Selection()


class Selectable:
    """Mixin: a tap selects this entity (orange border); every selectable follows the shared selection."""

    def _init_selectable(self, key: str):
        self.key = key
        self.setCursor(Qt.PointingHandCursor)
        SELECTION.changed.connect(self._on_selection)

    def _on_selection(self, keys: list):
        self.setProperty("selected", "true" if self.key in keys else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            SELECTION.picked.emit(self.key)


class EntityCard(Selectable, QFrame):
    """Image + official English name + key stats + credit; tap to ask about it, ↗ opens its NiaMeowDB page."""

    def __init__(self, kb: KnowledgeBase, key: str, lang: str):
        super().__init__()
        self.setObjectName("Card")
        self._init_selectable(key)
        self.setToolTip("לחצו כדי לשאול עליה" if lang == "he" else "Tap to ask about it")
        e = kb.get(key) or {}
        self.url = e.get("url")
        he = lang == "he"

        row = QHBoxLayout(self)
        row.setContentsMargins(10, 8, 10, 8)
        row.setSpacing(10)

        pic = QLabel()
        pic.setFixedSize(56, 56)
        pic.setAlignment(Qt.AlignCenter)
        img = kb.picture(key)          # never empty: own picture, related one, or category icon
        if img:
            pm = QPixmap(str(img))
            if not pm.isNull():
                pic.setPixmap(pm.scaled(56, 56, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        row.addWidget(pic, 0, Qt.AlignTop)

        col = QVBoxLayout()
        col.setSpacing(2)
        name = _label(e.get("name", key), "CardName", wrap=True)
        name.setLayoutDirection(Qt.LeftToRight)      # official English name, always LTR
        name.setAlignment(Qt.AlignLeft if not he else Qt.AlignRight)
        col.addWidget(name)

        cat = e.get("category", "")
        sub = CATEGORY_LABELS.get(cat, (cat, cat))[0 if he else 1]
        if e.get("type"):
            sub = f"{sub} · {e['type']}"
        # in Hebrew every line starts on the right, even an all-English one like "NPC"
        side = (Qt.AlignRight if he else Qt.AlignLeft) | Qt.AlignAbsolute
        sub_label = _label(bidi.plain(sub, he), "CardSub")
        sub_label.setAlignment(side)
        col.addWidget(sub_label)

        stats = self._stats(e, he)
        if stats:
            stat_label = _label(bidi.plain(stats, he), "CardStat")
            stat_label.setAlignment(side)
            col.addWidget(stat_label)
        credit = _label("NiaMeowDB (meowdb.com)", "CardCredit")
        col.addWidget(credit)
        row.addLayout(col, 1)
        if self.url:
            from PySide6.QtWidgets import QToolButton
            from . import theme
            link = QToolButton(objectName="Icon", text=theme.ICON["open"])
            link.setCursor(Qt.PointingHandCursor)
            link.setToolTip("NiaMeowDB")
            link.clicked.connect(lambda: webbrowser.open(self.url))
            row.addWidget(link, 0, Qt.AlignTop)

    @staticmethod
    def _stats(e: dict, he: bool) -> str:
        props = e.get("props") or {}
        bits = []
        for k in ("Level", "HP", "EXP", "Required Level", "Attack", "Weapon Attack", "Magic Attack", "Defense"):
            if k in props and props[k] not in (None, "", 0):
                label = {"Level": "לבל", "Required Level": "לבל נדרש"}.get(k, k) if he else k
                bits.append(f"{label}: {props[k]}")
            if len(bits) >= 3:
                break
        return " · ".join(bits)



# ------------------------------------------------------------------ profile card (pinned at the top of the chat)

from PySide6.QtCore import QRectF  # noqa: E402
from PySide6.QtGui import QColor, QPainter, QPainterPath  # noqa: E402

JOB_IMAGE_FALLBACK = {  # 3rd jobs have no picture in the database: use their 2nd job's
    "crusader": "fighter", "white-knight": "page", "dragon-knight": "spearman", "f-p-mage": "f-p-wizard",
    "i-l-mage": "i-l-wizard", "priest": "cleric", "ranger": "hunter", "sniper": "crossbowman",
    "hermit": "assassin", "chief-bandit": "bandit",
}


def _slug(job: str) -> str:
    return job.lower().replace("/", "-").replace(" ", "-")


class Avatar(QLabel):
    """Rounded-square portrait."""

    def __init__(self, size: int = 46):
        super().__init__()
        self.setFixedSize(size, size)
        self._pm = None

    def set_image(self, path) -> None:
        pm = QPixmap(str(path)) if path else QPixmap()
        self._pm = None if pm.isNull() else pm
        self.update()

    def paintEvent(self, e):
        from . import theme
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 12, 12)
        p.setClipPath(path)
        p.fillPath(path, QColor(255, 255, 255, 26) if theme.MODE == "dark" else QColor(0, 0, 0, 10))
        if self._pm:
            dpr = self.devicePixelRatioF()
            pm = self._pm.scaled(self.size() * dpr, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            pm.setDevicePixelRatio(dpr)
            w, h = pm.width() / dpr, pm.height() / dpr
            p.drawPixmap(int((self.width() - w) / 2), int((self.height() - h) / 2), pm)


class ProfileCard(QFrame):
    """Name, "Lv. 32 · Assassin" (English, as in game) and a live portrait of the character."""

    clicked = Signal()
    refresh_requested = Signal()

    def __init__(self):
        super().__init__(objectName="ProfileCard")
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 8, 12, 8)
        row.setSpacing(10)
        self.avatar = Avatar(46)
        row.addWidget(self.avatar)
        col = QVBoxLayout()
        col.setSpacing(1)
        self.name = QLabel(objectName="ProfileName")
        self.meta = QLabel(objectName="ProfileMeta")
        col.addWidget(self.name)
        col.addWidget(self.meta)
        row.addLayout(col, 1)
        from PySide6.QtWidgets import QToolButton
        from . import theme
        self.refresh = QToolButton(objectName="Refresh", text=theme.ICON["refresh"])
        self.refresh.setCursor(Qt.PointingHandCursor)
        self.refresh.clicked.connect(self.refresh_requested.emit)
        row.addWidget(self.refresh, 0, Qt.AlignVCenter)
        self._spin_frames = ["\ue72c", "\ue895"]      # refresh / sync glyphs alternate while busy
        from PySide6.QtCore import QTimer
        self._spin = QTimer(self, interval=260, timeout=self._tick)
        self._frame = 0

    def set_busy(self, busy: bool, tip: str = "") -> None:
        from . import theme
        self.refresh.setEnabled(not busy)
        if busy:
            self._spin.start()
        else:
            self._spin.stop()
            self.refresh.setText(theme.ICON["refresh"])
        if tip:
            self.refresh.setToolTip(tip)

    def _tick(self):
        self._frame = (self._frame + 1) % len(self._spin_frames)
        self.refresh.setText(self._spin_frames[self._frame])

    def show_character(self, c, avatar_path, kb, rtl: bool) -> None:
        align = (Qt.AlignRight if rtl else Qt.AlignLeft) | Qt.AlignAbsolute | Qt.AlignVCenter
        self.name.setText(bidi.plain(c.name, rtl))
        self.name.setAlignment(align)
        self.meta.setText(f"Lv. {c.level} · {c.job}")
        self.meta.setAlignment(align)
        self.avatar.set_image(character_image(c, avatar_path, kb))

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()


def character_image(c, avatar_path, kb):
    """The character's own portrait, else the picture of its job (or class)."""
    if avatar_path:
        return avatar_path
    slug = _slug(c.job)
    return kb.image_path(f"class/{JOB_IMAGE_FALLBACK.get(slug, slug)}") or kb.image_path(
        f"class/{_slug(c.base_class)}")


class CharacterRow(QFrame):
    chosen = Signal(str)
    edit_requested = Signal(str)
    delete_requested = Signal(str)

    def __init__(self, c, avatar_path, kb, active: bool, rtl: bool, can_delete: bool):
        super().__init__(objectName="CharacterRow")
        self.cid = c.id
        self.setCursor(Qt.PointingHandCursor)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 8, 0, 8)
        row.setSpacing(10)
        self.avatar = Avatar(36)
        img = avatar_path
        if not img:
            slug = _slug(c.job)
            img = kb.image_path(f"class/{JOB_IMAGE_FALLBACK.get(slug, slug)}") or kb.image_path(
                f"class/{_slug(c.base_class)}")
        self.avatar.set_image(img)
        row.addWidget(self.avatar)
        col = QVBoxLayout()
        col.setSpacing(0)
        align = (Qt.AlignRight if rtl else Qt.AlignLeft) | Qt.AlignAbsolute | Qt.AlignVCenter
        name = QLabel(bidi.plain(c.name, rtl), objectName="ProfileName")
        name.setAlignment(align)
        meta = QLabel(f"Lv. {c.level} · {c.job}", objectName="ProfileMeta")
        meta.setAlignment(align)
        col.addWidget(name)
        col.addWidget(meta)
        row.addLayout(col, 1)
        check = QLabel("✓" if active else "", objectName="Check")
        check.setFixedWidth(18)
        row.addWidget(check)
        from . import theme
        pencil = QPushButton(theme.ICON["edit"], objectName="IconPlain")
        pencil.setCursor(Qt.PointingHandCursor)
        pencil.clicked.connect(lambda: self.edit_requested.emit(self.cid))
        row.addWidget(pencil)
        if can_delete:
            trash = QPushButton(theme.ICON["delete"], objectName="IconDanger")
            trash.setCursor(Qt.PointingHandCursor)
            trash.clicked.connect(lambda: self.delete_requested.emit(self.cid))
            row.addWidget(trash)

    def mouseReleaseEvent(self, e):
        self.chosen.emit(self.cid)


class EntityTile(Selectable, QFrame):
    """Compact item tile for lists (drops, rewards): picture + official name. Tap to ask about it."""

    def __init__(self, kb, key: str):
        super().__init__(objectName="Tile")
        self._init_selectable(key)
        e = kb.get(key) or {}
        self.url = e.get("url")
        self.setToolTip(e.get("name", key))
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 6, 8, 6)
        row.setSpacing(8)
        pic = QLabel()
        pic.setFixedSize(32, 32)
        pic.setAlignment(Qt.AlignCenter)
        img = kb.picture(key)
        if img:
            pm = QPixmap(str(img))
            if not pm.isNull():
                pic.setPixmap(pm.scaled(32, 32, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        row.addWidget(pic)
        name = QLabel(e.get("name", key), objectName="TileName")
        name.setWordWrap(True)
        from PySide6.QtWidgets import QApplication
        rtl = QApplication.layoutDirection() == Qt.RightToLeft
        name.setAlignment((Qt.AlignRight if rtl else Qt.AlignLeft) | Qt.AlignAbsolute | Qt.AlignVCenter)
        row.addWidget(name, 1)



class TileGrid(QFrame):
    """Two-column grid of item tiles with a credit line."""

    def __init__(self, kb, keys: list[str], title: str = ""):
        super().__init__(objectName="TileGrid")
        from PySide6.QtWidgets import QApplication, QGridLayout
        from .. import bidi
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 6)
        outer.setSpacing(4)
        if title:
            rtl = QApplication.layoutDirection() == Qt.RightToLeft
            t = QLabel(bidi.plain(title, rtl), objectName="TileGridTitle")
            t.setAlignment((Qt.AlignRight if rtl else Qt.AlignLeft) | Qt.AlignAbsolute | Qt.AlignVCenter)
            t.setContentsMargins(4, 0, 4, 2)
            outer.addWidget(t)
        grid = QGridLayout()
        grid.setSpacing(6)
        for i, k in enumerate(keys):
            grid.addWidget(EntityTile(kb, k), i // 2, i % 2)
        outer.addLayout(grid)
        credit = QLabel("NiaMeowDB (meowdb.com)", objectName="CardCredit")
        outer.addWidget(credit)


class DropGroupCard(QFrame):
    """A monster and the items it drops: header row (picture, name, level) + item tiles."""

    def __init__(self, kb, monster: str, items: list[str]):
        super().__init__(objectName="TileGrid")
        from PySide6.QtWidgets import QApplication, QGridLayout
        rtl = QApplication.layoutDirection() == Qt.RightToLeft
        e = kb.get(monster) or {}
        self.url = e.get("url")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 8, 10, 8)
        outer.setSpacing(6)
        header = _GroupHeader(monster)
        outer.addWidget(header)
        head = QHBoxLayout(header)
        head.setContentsMargins(4, 2, 4, 2)
        head.setSpacing(10)
        pic = QLabel()
        pic.setFixedSize(40, 40)
        pic.setAlignment(Qt.AlignCenter)
        img = kb.picture(monster)
        if img:
            pm = QPixmap(str(img))
            if not pm.isNull():
                pic.setPixmap(pm.scaled(40, 40, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        head.addWidget(pic)
        align = (Qt.AlignRight if rtl else Qt.AlignLeft) | Qt.AlignAbsolute | Qt.AlignVCenter
        col = QVBoxLayout()
        col.setSpacing(0)
        name = QLabel(e.get("name", monster), objectName="CardName")
        name.setAlignment(align)
        lv = (e.get("props") or {}).get("Level")
        sub = QLabel(f"Lv. {lv}" if lv else "", objectName="CardSub")
        sub.setAlignment(align)
        col.addWidget(name)
        col.addWidget(sub)
        head.addLayout(col, 1)
        grid = QGridLayout()
        grid.setSpacing(6)
        for i, k in enumerate(items):
            grid.addWidget(EntityTile(kb, k), i // 2, i % 2)
        outer.addLayout(grid)


class _GroupHeader(Selectable, QFrame):
    def __init__(self, key: str):
        super().__init__(objectName="GroupHeader")
        self._init_selectable(key)
