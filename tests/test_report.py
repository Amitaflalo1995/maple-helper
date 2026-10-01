"""The problem report carries the log and diagnostics, never private data."""
import json
import logging
import zipfile

from maplehelper import report


def test_report_has_log_and_info_but_no_private_settings(tmp_path, monkeypatch):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "maplehelper.log").write_text("2026-10-01 INFO started\n", encoding="utf-8")
    monkeypatch.setattr(report, "LOG_DIR", logs)
    info = report.system_info("0.4.0", "2026.10.01.0100", "ok")
    path = report.build_report(tmp_path / "out", info, {"language": "he", "window": {"x": 1}, "bubble_pos": {}})
    with zipfile.ZipFile(path) as z:
        assert set(z.namelist()) == {"info.json", "settings.json", "logs/maplehelper.log"}
        assert json.loads(z.read("info.json"))["app_version"] == "0.4.0"
        assert json.loads(z.read("settings.json")) == {"language": "he"}


def test_logging_writes_to_the_log_file(tmp_path, monkeypatch):
    monkeypatch.setattr(report, "LOG_DIR", tmp_path)
    monkeypatch.setattr(report, "LOG_FILE", tmp_path / "maplehelper.log")
    root = logging.getLogger()
    before = list(root.handlers)
    try:
        for h in [h for h in root.handlers if isinstance(h, logging.handlers.RotatingFileHandler)]:
            root.removeHandler(h)
        report.setup_logging()
        logging.getLogger("maplehelper.test").info("hello log")
        for h in root.handlers:
            h.flush()
        assert "hello log" in (tmp_path / "maplehelper.log").read_text(encoding="utf-8")
    finally:
        for h in root.handlers[:]:
            if h not in before:
                root.removeHandler(h)
                h.close()
