"""The KB gate in front of every publish, and the packer (same manifest format as tools/release.py)."""
import hashlib
import json
import zipfile

import pytest

import kb_release


def test_fixture_kb_is_valid(kb_copy):
    summary = kb_release.validate(kb_copy)
    assert summary["count"] == 15 and set(summary["categories"]) == set(kb_release.CATEGORIES)


def test_rejects_unreadable_index(kb_copy):
    (kb_copy / "index.json").write_text("{", encoding="utf-8")
    with pytest.raises(kb_release.InvalidKB, match="unreadable"):
        kb_release.validate(kb_copy)


def test_rejects_too_few_entities_and_missing_categories(kb_copy):
    index = json.loads((kb_copy / "index.json").read_text(encoding="utf-8"))
    (kb_copy / "index.json").write_text(json.dumps([e for e in index if e["category"] == "monster"]), encoding="utf-8")
    with pytest.raises(kb_release.InvalidKB) as e:
        kb_release.validate(kb_copy, min_entities=10)
    assert "only 5 entities" in str(e.value) and "missing categories" in str(e.value)


def test_rejects_big_drop_from_previous(kb_copy, tmp_path):
    prev = tmp_path / "prev-index.json"
    prev.write_text(json.dumps([{"key": f"x/{i}"} for i in range(100)]), encoding="utf-8")
    with pytest.raises(kb_release.InvalidKB, match="down from 100"):
        kb_release.validate(kb_copy, previous_index=prev)


def test_small_drop_is_fine(kb_copy, tmp_path):
    prev = tmp_path / "prev-index.json"
    prev.write_text(json.dumps([{"key": f"x/{i}"} for i in range(16)]), encoding="utf-8")
    assert kb_release.validate(kb_copy, previous_index=prev)["count"] == 15


def test_rejects_missing_pages(kb_copy):
    (kb_copy / "pages" / "monster" / "130101.md").unlink()
    with pytest.raises(kb_release.InvalidKB, match="1 entries without a page"):
        kb_release.validate(kb_copy)


def test_pack_writes_zip_and_matching_manifest(kb_copy, tmp_path):
    out = tmp_path / "dist"
    m = kb_release.pack(kb_copy, out, version="2026.10.02.1200")
    assert m["version"] == "2026.10.02.1200"
    assert m["url"] == "https://github.com/Amitaflalo1995/maple-helper/releases/latest/download/kb.zip"
    assert hashlib.sha256((out / "kb.zip").read_bytes()).hexdigest() == m["sha256"]
    assert json.loads((out / "kb-manifest.json").read_text(encoding="utf-8")) == m
    with zipfile.ZipFile(out / "kb.zip") as z:
        names = z.namelist()
        assert "index.json" in names and "pages/monster/130101.md" in names   # files at the zip root
        assert json.loads(z.read("meta.json"))["version"] == "2026.10.02.1200"


def test_packed_kb_installs_through_the_real_updater(kb_copy, tmp_path, monkeypatch):
    """End to end: what CI packs is exactly what installed apps accept."""
    from maplehelper import updater
    out = tmp_path / "dist"
    m = kb_release.pack(kb_copy, out)
    net = {updater.MANIFEST_URL: (out / "kb-manifest.json").read_bytes(), m["url"]: (out / "kb.zip").read_bytes()}
    user_kb = tmp_path / "user-kb"
    monkeypatch.setattr(updater, "_get", lambda url, timeout=30: net.get(url))
    monkeypatch.setattr(updater, "USER_KB", user_kb)
    monkeypatch.setattr(updater, "kb_dir", lambda: user_kb)
    assert updater.update_kb() is True
    assert updater.local_version() == m["version"]
    assert len(json.loads((user_kb / "index.json").read_text(encoding="utf-8"))) == 15


def test_default_version_sorts_as_string(kb_copy, tmp_path):
    m = kb_release.pack(kb_copy, tmp_path / "d")
    assert len(m["version"]) == len("2026.10.02.1200") and m["version"] > "2000.01.01.0000"


def test_cli_exit_codes(kb_copy, capsys):
    assert kb_release.main(["validate", str(kb_copy)]) == 0
    assert kb_release.main(["validate", str(kb_copy), "--min-entities", "999"]) == 1
    assert "::error::" in capsys.readouterr().out
