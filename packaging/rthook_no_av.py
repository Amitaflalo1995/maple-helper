# faster-whisper imports PyAV only to decode audio files; Maple Helper passes raw
# microphone samples, so a stub keeps ~65MB of FFmpeg out of the installer.
import sys
import types

if "av" not in sys.modules:
    sys.modules["av"] = types.ModuleType("av")
