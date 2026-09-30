"""Mixed Hebrew/English rendering, measured on real glyph positions from Qt's text engine.

Each case lists pairs (a, b) that must satisfy: a is drawn to the LEFT of b.
In RTL text, brackets are mirrored, so the logical "(" is drawn on the right.

Run: .venv\\Scripts\\python -m pytest tests -q
"""
import sys

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QTextLayout, QTextOption
from PySide6.QtWidgets import QApplication

from maplehelper import bidi

app = QApplication.instance() or QApplication(sys.argv)

CASES = [
    ("בונוס +5 STR לכובע.", [("+", "5"), ("5", "S")]),
    ("סיכוי 10–20% לדרופ.", [("1", "–"), ("–", "%")]),
    ("מפלצת (Lv. 10) חזקה.", [("L", "1"), (")", "1"), ("L", "(")]),
    ("תלך ל-Red Snail.", [(".", "R"), ("R", "S")]),
    ("בונוס של 5% ל-HP ו-MP.", [(".", "M"), ("M", "ו"), ("H", "P")]),
    ("Red Snail הוא יעד טוב.", [("R", "S"), (".", "R")]),
    ("המפה Henesys Hunting Ground I היא הכי טובה", [("H", "G"), ("G", "I")]),
    ("לחץ F9 כדי לפתוח ו-F10 כדי לדבר.", [(".", "F")]),
    ("צריך 30 EXP כדי לעלות לבל.", [(".", "צ"), ("3", "E")]),
    ("ה-Orange Mushroom מפיל Mushroom Cap?", [("?", "M"), ("O", "M")]),
    ("עלית ללבל 35! עכשיו לך ל-Perion.", [(".", "P"), ("3", "5")]),
    ("הסקיל Power Strike (Lv. 20) הכי חשוב.", [("P", "S"), ("L", "2")]),
    ("מחיר: 1,500 mesos בחנות.", [("1", "5"), ("5", "m")]),
    ("בכפפות האלה יש ATT +3 ו-DEF +10.", [("A", "3"), (".", "D")]),
    ("נמצא ב-The Forest North of Ellinia (Victoria Road).", [(".", "T"), ("T", "V"), ("E", "R")]),
    ("כדאי לגרינד על Axe Stump (לבל 17, 371 HP, 32 EXP).", [("A", "S"), ("3", "H"), (".", "E")]),
    ("המפות East Rocky Mountain II/III מעולות.", [("E", "M"), ("M", "/")]),
]


def glyph_x(text: str) -> dict[int, float]:
    lay = QTextLayout(text, QFont("Arial", 20))
    opt = QTextOption()
    opt.setTextDirection(Qt.RightToLeft)
    lay.setTextOption(opt)
    lay.beginLayout()
    line = lay.createLine()
    line.setLineWidth(3000)
    lay.endLayout()
    flags = QTextLayout.GlyphRunRetrievalFlag.RetrieveGlyphPositions | QTextLayout.GlyphRunRetrievalFlag.RetrieveStringIndexes
    pos: dict[int, float] = {}
    for run in lay.glyphRuns(0, len(text), flags):
        for p, si in zip(run.positions(), run.stringIndexes()):
            pos.setdefault(si, p.x())
    return pos


@pytest.mark.parametrize("sentence,checks", CASES)
def test_mixed_sentence_renders_in_reading_order(sentence, checks):
    assert bidi.direction(sentence) == "rtl"
    shown = bidi.isolate_ltr_runs(sentence)
    x = glyph_x(shown)
    for a, b in checks:
        assert x[shown.index(a)] < x[shown.index(b)], f"{a!r} should be left of {b!r} in {sentence!r}"


def test_direction_per_paragraph():
    assert bidi.direction("where is Henesys?") == "ltr"
    assert bidi.direction("איפה Henesys?") == "rtl"
    assert bidi.direction("Red Snail הוא יעד טוב לגרינד") == "rtl"


def test_html_direction_follows_the_message():
    he = bidi.to_html("**Red Snail** הוא יעד טוב.\n• HP: 371\nThis drop is really rare in Classic.")
    assert he.count('dir="rtl"') == 2 and he.count('dir="ltr"') == 1 and "<b>" in he
    en = bidi.to_html("Go grind **Red Snail** now.\nIt drops Red Potion.")
    assert 'dir="rtl"' not in en
