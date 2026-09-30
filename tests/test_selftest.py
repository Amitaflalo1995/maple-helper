"""The self-test that CI runs against the built exe also works from source."""
import subprocess
import sys

from maplehelper import selftest


def test_selftest_passes_from_source(tmp_path):
    report = tmp_path / "report.txt"
    # separate process: the self-test creates its own (offscreen) QApplication
    r = subprocess.run([sys.executable, "-c", "import sys; from maplehelper import app; sys.exit(app.main())",
                        f"--selftest={report}"], capture_output=True, timeout=180)
    text = report.read_text(encoding="utf-8")
    assert r.returncode == 0, text
    assert "SELFTEST OK" in text and "ok   import faster_whisper" in text


def test_require_kb_fails_on_empty_kb(monkeypatch, tmp_path):
    from maplehelper import kb
    monkeypatch.setattr(kb, "kb_dir", lambda: tmp_path)
    ok, lines = selftest.run(require_kb=True)
    assert not ok and any(ln.startswith("FAIL knowledge base") for ln in lines)
