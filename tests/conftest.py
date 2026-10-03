"""Shared test setup.

maplehelper.store creates folders under %APPDATA% at import time, so APPDATA is
pointed at a throwaway folder here, before any test imports the app. Tests never
touch a real player's settings, profiles or history.
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ["APPDATA"] = tempfile.mkdtemp(prefix="maplehelper-tests-")
# every window a test makes stays off the screen (one test file without this flashed a real Settings window)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
# telemetry.py ships a real PostHog key: no test may send real usage stats
# (test_telemetry.py lifts this for itself and mocks the network instead)
os.environ["MAPLEHELPER_NO_TELEMETRY"] = "1"
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import pytest  # noqa: E402

FIXTURE_KB = Path(__file__).parent / "fixtures" / "kb"


@pytest.fixture
def kb_copy(tmp_path) -> Path:
    """A writable copy of the fixture knowledge base."""
    dst = tmp_path / "kb"
    shutil.copytree(FIXTURE_KB, dst)
    return dst


@pytest.fixture
def kb():
    from maplehelper.kb import KnowledgeBase
    return KnowledgeBase(FIXTURE_KB)


@pytest.fixture
def isolated_store(tmp_path, monkeypatch):
    """Settings/Profiles/History write into tmp_path instead of the shared test APPDATA."""
    from maplehelper import store
    monkeypatch.setattr(store.Settings, "path", tmp_path / "settings.json")
    monkeypatch.setattr(store.Profiles, "path", tmp_path / "profiles.json")
    monkeypatch.setattr(store, "HISTORY_DIR", tmp_path / "history")
    (tmp_path / "history").mkdir()
    return store
