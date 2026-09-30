"""Push-to-talk: hold the voice key, speak, release. Transcription runs locally.

Model: ivrit.ai's Hebrew-tuned Whisper large-v3-turbo (CTranslate2), which also
handles English. Downloaded once on first use (~1.6GB) into %APPDATA%.
GPU (CUDA) when available, otherwise CPU int8.
"""
from __future__ import annotations

import threading

import numpy as np
from PySide6.QtCore import QObject, QTimer, Signal

from . import winapi
from .store import DATA_DIR

MODEL_ID = "ivrit-ai/whisper-large-v3-turbo-ct2"
SAMPLE_RATE = 16_000
MIN_SECONDS = 0.4
POLL_MS = 30


class Transcriber:
    def __init__(self):
        self._model = None
        self._lock = threading.Lock()

    def loaded(self) -> bool:
        return self._model is not None

    def load(self):
        with self._lock:
            if self._model is not None:
                return
            from faster_whisper import WhisperModel
            root = str(DATA_DIR / "models")
            try:
                self._model = WhisperModel(MODEL_ID, device="cuda", compute_type="float16", download_root=root)
                # a tiny decode proves the GPU runtime actually works
                self._model.transcribe(np.zeros(SAMPLE_RATE // 2, dtype=np.float32))
            except Exception:
                self._model = WhisperModel(MODEL_ID, device="cpu", compute_type="int8", download_root=root)

    def transcribe(self, audio: np.ndarray) -> str:
        self.load()
        segments, _info = self._model.transcribe(audio, beam_size=5, vad_filter=True,
                                                 initial_prompt="MapleStory Classic, Henesys, Ellinia, Perion, "
                                                                "Kerning City, Red Snail, Orange Mushroom, לבל, ג'וב")
        return " ".join(s.text.strip() for s in segments).strip()


class VoiceController(QObject):
    """Polls the push-to-talk key (no keyboard hook) and records while it is held."""

    started = Signal()
    state = Signal(str)          # listening | transcribing | loading | idle
    text = Signal(str)
    failed = Signal(str)

    def __init__(self, key_name: str = "F10"):
        super().__init__()
        self.key_name = key_name
        self.transcriber = Transcriber()
        self._held = False
        self._chunks: list[np.ndarray] = []
        self._stream = None
        self._timer = QTimer(self, interval=POLL_MS, timeout=self._poll)
        self._timer.start()

    def set_key(self, key_name: str):
        self.key_name = key_name

    def _poll(self):
        down = winapi.key_down(self.key_name)
        if down and not self._held:
            self._held = True
            self._start()
        elif not down and self._held:
            self._held = False
            self._stop()

    def _start(self):
        try:
            import sounddevice as sd
            self._chunks = []
            self._stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                                          callback=lambda data, *_: self._chunks.append(data.copy()))
            self._stream.start()
        except Exception as e:
            self.failed.emit(f"mic: {e}")
            return
        self.started.emit()
        self.state.emit("listening")

    def _stop(self):
        if not self._stream:
            return
        self._stream.stop()
        self._stream.close()
        self._stream = None
        audio = np.concatenate(self._chunks)[:, 0] if self._chunks else np.zeros(0, dtype=np.float32)
        if len(audio) < SAMPLE_RATE * MIN_SECONDS:
            self.state.emit("idle")
            return
        self.state.emit("transcribing" if self.transcriber.loaded() else "loading")
        threading.Thread(target=self._run, args=(audio,), daemon=True).start()

    def _run(self, audio: np.ndarray):
        try:
            out = self.transcriber.transcribe(audio)
            self.text.emit(out)
        except Exception as e:
            self.failed.emit(str(e))
        finally:
            self.state.emit("idle")
