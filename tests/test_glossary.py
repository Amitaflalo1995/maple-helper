"""The "?" beside game terms: every term the app marks has an explanation, and marking never breaks
the order of an English block inside Hebrew."""
from maplehelper import bidi, glossary


def test_every_marked_term_is_explained_in_both_languages():
    for term in glossary.TERMS:
        assert glossary.explain(term, "he"), term
        assert glossary.explain(term, "en"), term


def test_only_the_first_appearance_is_marked():
    out = glossary.annotate("<p>ACC 47 and ACC 50, EXP 45</p>", "en")
    assert out.count("g:ACC") == 1 and out.count("g:EXP") == 1
    assert glossary.annotate("<a href='x'>ACC</a>", "en").count("g:ACC") == 0     # never inside a link


def test_marks_go_after_an_english_block_in_hebrew():
    line = bidi.isolate_ltr_runs("יש לה Avoid 14 בלבד")
    out = glossary.annotate(line, "he")
    run = f"{bidi.LRE}Avoid 14{bidi.PDF}"
    assert run in out and out.index("g:Avoid") > out.index(run)
