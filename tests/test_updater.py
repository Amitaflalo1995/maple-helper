"""Knowledge-base updates: only a newer, intact, hash-verified KB ever replaces the current one."""
import hashlib
import io
import json
import zipfile

import pytest

from maplehelper import updater

MANIFEST = "https://example.test/kb-manifest.json"
ZIP_URL = "https://example.test/kb.zip"


def make_zip(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, text in files.items():
            z.writestr(name, text)
    return buf.getvalue()


GOOD_ZIP = make_zip({"index.json": "[]", "meta.json": '{"source": "test"}', "pages/monster/1.md": "# x"})


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A fake network plus a user KB folder under tmp_path, currently at version 2026.01.01."""
    user_kb = tmp_path / "kb"
    user_kb.mkdir()
    (user_kb / "index.json").write_text('[{"key": "old"}]', encoding="utf-8")
    (user_kb / "meta.json").write_text('{"version": "2026.01.01.0000"}', encoding="utf-8")
    monkeypatch.setattr(updater, "USER_KB", user_kb)
    monkeypatch.setattr(updater, "kb_dir", lambda: user_kb)
    monkeypatch.setattr(updater, "MANIFEST_URL", MANIFEST)
    net: dict[str, bytes | None] = {}
    monkeypatch.setattr(updater, "_get", lambda url, timeout=30: net.get(url))

    def publish(version="2026.02.01.0000", data=GOOD_ZIP, sha=None, **extra):
        m = {"version": version, "url": ZIP_URL, "sha256": sha or hashlib.sha256(data).hexdigest(), **extra}
        net[MANIFEST] = json.dumps(m).encode()
        net[ZIP_URL] = data
    return user_kb, net, publish


def still_old(user_kb):
    return json.loads((user_kb / "index.json").read_text(encoding="utf-8")) == [{"key": "old"}]


def test_newer_kb_is_installed_and_versioned(env):
    user_kb, _, publish = env
    publish()
    assert updater.update_kb() is True
    assert json.loads((user_kb / "index.json").read_text(encoding="utf-8")) == []
    assert updater.local_version() == "2026.02.01.0000"
    assert not user_kb.with_name("kb.new").exists()


@pytest.mark.parametrize("version", ["2026.01.01.0000", "2025.12.31.2359"])
def test_same_or_older_version_is_skipped(env, version):
    user_kb, _, publish = env
    publish(version=version)
    assert updater.update_kb() is False and still_old(user_kb)


def test_hash_mismatch_is_rejected(env):
    user_kb, _, publish = env
    publish(sha="0" * 64)
    assert updater.update_kb() is False and still_old(user_kb)


def test_zip_without_index_is_rejected(env):
    user_kb, _, publish = env
    publish(data=make_zip({"meta.json": "{}"}))
    assert updater.update_kb() is False and still_old(user_kb)
    assert not user_kb.with_name("kb.new").exists()


def test_corrupt_zip_with_matching_hash_is_rejected(env):
    user_kb, _, publish = env
    publish(data=b"this is not a zip")
    assert updater.update_kb() is False and still_old(user_kb)


@pytest.mark.parametrize("manifest", [None, b"{not json", b"[]", b'{"version": "2099.01.01"}'])
def test_offline_or_bad_manifest(env, manifest):
    user_kb, net, _ = env
    net[MANIFEST] = manifest
    assert updater.update_kb() is False and still_old(user_kb)


def test_download_failure(env):
    user_kb, net, publish = env
    publish()
    net[ZIP_URL] = None
    assert updater.update_kb() is False and still_old(user_kb)


def test_manifest_url_uses_latest_release():
    # every release that can become "latest" must carry kb-manifest.json (see docs/RELEASING.md)
    assert updater.MANIFEST_URL.endswith("/releases/latest/download/kb-manifest.json")


# ---------------------------------------------------------------- app self-update

API = "https://api.github.com/repos/Amitaflalo1995/maple-helper/releases/latest"
SETUP = b"MZ fake installer bytes"


@pytest.fixture
def app_env(tmp_path, monkeypatch):
    """A fake GitHub API + release assets; downloads land under tmp_path."""
    monkeypatch.setattr(updater, "USER_KB", tmp_path / "kb")
    net: dict[str, bytes | None] = {}
    monkeypatch.setattr(updater, "_get", lambda url, timeout=30: net.get(url))

    def publish(tag="v0.2.0", setup=SETUP, sums=None, include_sums=True, **extra):
        sums = sums if sums is not None else f"{hashlib.sha256(setup).hexdigest()}  MapleHelper-Setup.exe\n"
        assets = [{"name": "MapleHelper-Setup.exe", "browser_download_url": "https://dl/setup", "size": len(setup)}]
        if include_sums:
            assets.append({"name": "SHA256SUMS.txt", "browser_download_url": "https://dl/sums"})
        net[API] = json.dumps({"tag_name": tag, "assets": assets, **extra}).encode()
        net["https://dl/setup"] = setup
        net["https://dl/sums"] = sums.encode()
    return tmp_path, net, publish


def test_verified_installer_is_downloaded(app_env):
    tmp, _, publish = app_env
    publish()
    path = updater.download_app_update("0.1.0")
    assert path and open(path, "rb").read() == SETUP
    assert path.endswith("MapleHelper-Setup-v0.2.0.exe")


def test_installer_with_wrong_hash_is_never_kept(app_env):
    tmp, _, publish = app_env
    publish(sums=f"{'0' * 64}  MapleHelper-Setup.exe\n")
    assert updater.download_app_update("0.1.0") is None
    assert not (tmp / "updates").exists()


def test_same_size_corruption_is_caught(app_env):
    # the old size-only check accepted this: same length, different bytes
    tmp, net, publish = app_env
    publish()
    net["https://dl/setup"] = bytes(len(SETUP))
    assert updater.download_app_update("0.1.0") is None


@pytest.mark.parametrize("kwargs", [
    {"include_sums": False},                                  # release without checksums
    {"sums": "garbage\n"},
    {"sums": f"{'a' * 64}  SomethingElse.exe\n"},             # checksum for another file only
])
def test_no_trusted_checksum_means_no_update(app_env, kwargs):
    _, _, publish = app_env
    publish(**kwargs)
    assert updater.download_app_update("0.1.0") is None


@pytest.mark.parametrize("kwargs,current", [
    ({"tag": "v0.1.0"}, "0.1.0"),                             # same version
    ({"tag": "v0.0.9"}, "0.1.0"),
    ({"tag": "v0.2.0", "prerelease": True}, "0.1.0"),
    ({"tag": "v0.2.0", "draft": True}, "0.1.0"),
])
def test_nothing_newer(app_env, kwargs, current):
    _, _, publish = app_env
    publish(**kwargs)
    assert updater.download_app_update(current) is None


def test_numeric_version_order(app_env):
    _, _, publish = app_env
    publish(tag="v0.10.0")
    assert updater.download_app_update("0.9.0") is not None


@pytest.mark.parametrize("api", [None, b"{oops", b"[]", b'{"message": "Not Found"}'])
def test_offline_or_odd_api_answers(app_env, api):
    _, net, _ = app_env
    net[API] = api
    assert updater.download_app_update("0.1.0") is None


def test_sums_line_with_binary_marker(app_env):
    _, _, publish = app_env
    publish(sums=f"{hashlib.sha256(SETUP).hexdigest()} *MapleHelper-Setup.exe\n")
    assert updater.download_app_update("0.1.0") is not None


def test_mac_update_notice_names_the_new_release(app_env):
    _, _, publish = app_env
    publish(tag="v0.4.0", html_url="https://github.com/Amitaflalo1995/maple-helper/releases/tag/v0.4.0")
    assert updater.newer_release("0.3.0") == ("0.4.0", "https://github.com/Amitaflalo1995/maple-helper/releases/tag/v0.4.0")


@pytest.mark.parametrize("kwargs", [{"tag": "v0.3.0"}, {"tag": "v0.4.0", "prerelease": True}])
def test_mac_update_notice_stays_quiet(app_env, kwargs):
    _, _, publish = app_env
    publish(**kwargs)
    assert updater.newer_release("0.3.0") is None


def test_update_now_reopens_the_app_with_the_chat():
    path = r"C:\x\updates\MapleHelper-Setup-v0.4.0.exe"
    assert updater.installer_version(path) == "0.4.0"
    assert updater.installer_args(path, reopen=True)[-1] == "/LAUNCHARGS=--updated"
    # an update on quit restarts quietly in the tray (the installer's default)
    assert not any(a.startswith("/LAUNCHARGS") for a in updater.installer_args(path, reopen=False))


def test_installer_relaunch_honours_the_launch_args():
    from pathlib import Path
    iss = (Path(__file__).resolve().parent.parent / "packaging" / "installer.iss").read_text(encoding="utf-8")
    assert 'Parameters: "{param:LAUNCHARGS|--background}"' in iss


def test_kb_in_use_is_kept_whole_and_retried_later(env, monkeypatch):
    # Windows refuses to rename a folder another process works in (the AI runs inside the KB)
    user_kb, _, publish = env
    publish()
    real_rename = type(user_kb).rename

    def busy(self, target):
        if self == user_kb:
            raise PermissionError("in use")
        return real_rename(self, target)
    monkeypatch.setattr(type(user_kb), "rename", busy)
    assert updater.update_kb() is False and still_old(user_kb)
    assert not user_kb.with_name("kb.new").exists()
