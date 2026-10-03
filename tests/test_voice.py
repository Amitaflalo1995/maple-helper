"""The voice model: downloaded once, then only loaded (also after app updates)."""
import pytest

pytest.importorskip("PySide6")

from maplehelper import voice  # noqa: E402


def test_downloaded_once_the_model_is_on_disk(tmp_path, monkeypatch):
    monkeypatch.setattr(voice, "DATA_DIR", tmp_path)
    assert not voice.Transcriber.downloaded()
    snap = tmp_path / "models" / "models--ivrit-ai--whisper-large-v3-turbo-ct2" / "snapshots" / "abc"
    snap.mkdir(parents=True)
    assert not voice.Transcriber.downloaded()          # an interrupted download has no model.bin yet
    (snap / "model.bin").write_bytes(b"x")
    assert voice.Transcriber.downloaded()


@pytest.mark.parametrize("on_disk,state", [(True, "loading"), (False, "downloading")])
def test_first_question_says_loading_not_downloading_when_on_disk(on_disk, state, monkeypatch):
    import numpy as np
    vc = voice.VoiceController()
    monkeypatch.setattr(voice.Transcriber, "downloaded", staticmethod(lambda: on_disk))
    monkeypatch.setattr(vc, "_run", lambda audio: None)
    monkeypatch.setattr(voice.threading, "Thread", lambda target, args, daemon: type("T", (), {"start": lambda s: target(*args)})())

    class Stream:
        def stop(self): pass
        def close(self): pass
    vc._stream = Stream()
    # a little noise, as any real mic gives: pure digital silence is macOS's "no microphone permission"
    vc._chunks = [np.full((voice.SAMPLE_RATE, 1), 0.01, dtype=np.float32)]
    states = []
    vc.state.connect(states.append)
    vc._stop()
    assert states == [state]


def test_preload_only_when_the_model_is_on_disk(monkeypatch):
    vc = voice.VoiceController()
    started = []
    monkeypatch.setattr(voice.threading, "Thread", lambda target, daemon: type("T", (), {"start": lambda s: started.append(target)})())
    monkeypatch.setattr(voice.Transcriber, "downloaded", staticmethod(lambda: False))
    vc.preload()
    assert started == []                                # never a 1.6GB download nobody asked for
    monkeypatch.setattr(voice.Transcriber, "downloaded", staticmethod(lambda: True))
    vc.preload()
    assert len(started) == 1


class _Stream:
    def stop(self): pass
    def close(self): pass


def test_mac_silence_is_a_microphone_permission_hint(monkeypatch):
    """macOS records pure zeros while the microphone isn't allowed: say so, not "I didn't hear anything"."""
    import numpy as np
    vc = voice.VoiceController()
    monkeypatch.setattr(voice.sys, "platform", "darwin")
    monkeypatch.setattr(vc, "_run", lambda audio: pytest.fail("silence must not be transcribed"))
    failed, states = [], []
    vc.failed.connect(failed.append)
    vc.state.connect(states.append)
    vc._stream = _Stream()
    vc._chunks = [np.zeros((voice.SAMPLE_RATE, 1), dtype=np.float32)]
    vc._stop()
    assert failed and failed[0].startswith("mic:") and states == ["idle"]


def test_mac_denied_microphone_is_reported_before_recording(monkeypatch):
    from maplehelper import macapi
    vc = voice.VoiceController()
    monkeypatch.setattr(voice.sys, "platform", "darwin")
    monkeypatch.setattr(macapi, "microphone_denied", lambda: True)
    failed = []
    vc.failed.connect(failed.append)
    vc._start()
    assert failed and failed[0].startswith("mic:") and vc._stream is None
