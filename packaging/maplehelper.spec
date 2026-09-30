# PyInstaller spec: builds dist/Maple Helper/ (onedir; the installer wraps it).
# Run from the repo root:  .venv\Scripts\pyinstaller packaging\maplehelper.spec --noconfirm
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH).parent

datas = [(str(ROOT / "assets"), "assets")]
kb = ROOT / "data" / "kb"
if (kb / "index.json").exists():
    datas.append((str(kb), "data/kb"))

binaries, hiddenimports = [], ["keyring.backends.Windows"]
for pkg in ("faster_whisper", "ctranslate2", "sounddevice"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    runtime_hooks=[str(ROOT / "packaging" / "rthook_no_av.py")],
    excludes=["av", "hf_xet", "tkinter", "torch", "tensorflow", "matplotlib", "pytest", "PySide6.QtWebEngineCore",
              "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore", "PySide6.QtQuick", "PySide6.QtQml"],
    noarchive=False,
)
# drop heavy binaries the app never loads
DROP = ("opengl32sw", "Qt6Quick", "Qt6Qml", "Qt6Pdf", "Qt6VirtualKeyboard", "Qt6OpenGL", "av.libs", "avcodec",
        "avformat", "avutil", "swresample", "swscale", "avfilter", "avdevice")
a.binaries = [b for b in a.binaries if not any(d.lower() in b[0].lower() for d in DROP)]
a.datas = [d for d in a.datas if not d[0].replace("\\", "/").startswith(("PySide6/translations/qtwebengine",))]

pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Maple Helper",
    icon=str(ROOT / "assets" / "brand" / "app.ico"),
    version=str(ROOT / "packaging" / "version_info.txt"),
    console=False,
    disable_windowed_traceback=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Maple Helper", strip=False, upx=False)
