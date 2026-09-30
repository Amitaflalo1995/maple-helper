"""Build and publish a release: exe (PyInstaller) → installer (Inno Setup) → GitHub Release
with MapleHelper-Setup.exe, kb.zip and kb-manifest.json.

Usage:
    python tools/release.py 0.1.0            # full release (app + knowledge base)
    python tools/release.py --kb-only        # refresh kb.zip/kb-manifest.json on the latest release
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
KB = ROOT / "data" / "kb"
ISCC = Path.home() / "AppData" / "Local" / "Programs" / "Inno Setup 6" / "ISCC.exe"
PY = ROOT / ".venv" / "Scripts" / "python.exe"
REPO = "Amitaflalo1995/maple-helper"


def run(cmd, **kw):
    print("›", " ".join(str(c) for c in cmd))
    subprocess.run(cmd, check=True, cwd=ROOT, **kw)


def set_version(version: str) -> None:
    init = ROOT / "maplehelper" / "__init__.py"
    init.write_text(re.sub(r'__version__ = "[^"]+"', f'__version__ = "{version}"', init.read_text(encoding="utf-8")),
                    encoding="utf-8")
    vi = ROOT / "packaging" / "version_info.txt"
    parts = (version.split(".") + ["0", "0", "0"])[:3]
    t = vi.read_text(encoding="utf-8")
    t = re.sub(r"filevers=\([^)]*\)", f"filevers=({', '.join(parts)}, 0)", t)
    t = re.sub(r"prodvers=\([^)]*\)", f"prodvers=({', '.join(parts)}, 0)", t)
    t = re.sub(r"'(FileVersion|ProductVersion)', '[^']*'", rf"'\1', '{version}'", t)
    vi.write_text(t, encoding="utf-8")


def build_kb() -> tuple[Path, Path]:
    version = time.strftime("%Y.%m.%d.%H%M")
    meta = json.loads((KB / "meta.json").read_text(encoding="utf-8")) if (KB / "meta.json").exists() else {}
    meta["version"] = version
    (KB / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    zpath = DIST / "kb.zip"
    DIST.mkdir(exist_ok=True)
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in KB.rglob("*"):
            if f.is_file():
                z.write(f, f.relative_to(KB))
    sha = hashlib.sha256(zpath.read_bytes()).hexdigest()
    manifest = DIST / "kb-manifest.json"
    manifest.write_text(json.dumps({"version": version, "sha256": sha,
                                    "url": f"https://github.com/{REPO}/releases/latest/download/kb.zip"}),
                        encoding="utf-8")
    print(f"kb {version}: {zpath.stat().st_size / 1e6:.1f} MB")
    return zpath, manifest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("version", nargs="?")
    ap.add_argument("--kb-only", action="store_true")
    ap.add_argument("--notes", default="")
    args = ap.parse_args()

    kb_zip, manifest = build_kb()
    if args.kb_only:
        tag = subprocess.run(["gh", "release", "view", "--repo", REPO, "--json", "tagName", "-q", ".tagName"],
                             capture_output=True, text=True, check=True).stdout.strip()
        run(["gh", "release", "upload", tag, str(kb_zip), str(manifest), "--clobber", "--repo", REPO])
        return

    if not args.version:
        sys.exit("version required, e.g. 0.1.0")
    set_version(args.version)
    run([PY, "-m", "pytest", "tests", "-q"])
    run([PY, "-m", "PyInstaller", "packaging/maplehelper.spec", "--noconfirm", "--distpath", "dist", "--workpath", "build"])
    report = DIST / "selftest.txt"
    # the self-test's verdict is its exit code (run() raises on failure); the report says why
    try:
        run([DIST / "Maple Helper" / "Maple Helper.exe", "--selftest", report, "--require-kb"])
    finally:
        if report.exists():
            print(report.read_text(encoding="utf-8"))
    run([ISCC, f"/DAppVersion={args.version}", "/Q", "packaging/installer.iss"])
    setup = DIST / "MapleHelper-Setup.exe"
    # the in-app updater only runs an installer whose hash matches the release's SHA256SUMS.txt
    sums = DIST / "SHA256SUMS.txt"
    sums.write_text(f"{hashlib.sha256(setup.read_bytes()).hexdigest()}  {setup.name}\n", encoding="ascii")
    notes = args.notes or f"Maple Helper {args.version}"
    run(["gh", "release", "create", f"v{args.version}", str(setup), str(sums), str(kb_zip), str(manifest),
         "--repo", REPO, "--title", f"Maple Helper {args.version}", "--notes", notes])


if __name__ == "__main__":
    main()
