import builtins
import wave
from types import SimpleNamespace

import pytest

from seance.audio import SAMPLE_RATE, clip_bounds, record_wav, write_wav
from seance.transcribe import Transcriber


def test_write_wav_is_16khz_mono(tmp_path):
    p = tmp_path / "a.wav"
    write_wav(p, b"\x00\x00" * 800)
    with wave.open(str(p)) as wf:
        assert (wf.getnchannels(), wf.getsampwidth(), wf.getframerate(), wf.getnframes()) == (1, 2, SAMPLE_RATE, 800)


def test_clip_bounds():
    assert clip_bounds(10, 20) == (9.6, 20.4)
    assert clip_bounds(None, None) == (0.0, 12.4)
    assert clip_bounds(0, 500) == (0.0, 30.0)


def test_missing_sounddevice_gives_install_hint(tmp_path, monkeypatch):
    real = builtins.__import__

    def fake(name, *a, **k):
        if name == "sounddevice":
            raise ImportError("nope")
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake)
    with pytest.raises(RuntimeError, match="pip install sounddevice numpy"):
        record_wav(tmp_path / "x.wav", seconds=1)


class FakeWhisper:
    def __init__(self, error=None):
        self.error = error
        self.tasks = []

    def transcribe(self, path, language=None, task="transcribe", **kw):
        if self.error:
            raise self.error
        self.tasks.append(task)
        text = "hello there" if task == "transcribe" else "hello in english"
        segs = iter([SimpleNamespace(text=f" {text} ", start=0.0, end=2.5), SimpleNamespace(text=" ", start=2.5, end=3)])
        return segs, SimpleNamespace(language="ml", duration=3.0)


def test_transcriber_keeps_segments_and_translates(monkeypatch):
    t = Transcriber()
    fake = FakeWhisper()
    t._model = fake
    out = t.transcribe("x.wav", translate=True)
    assert [s.text for s in out.segments] == ["hello there"]
    assert out.segments[0].end == 2.5
    assert [s.text for s in out.translation] == ["hello in english"]
    assert fake.tasks == ["transcribe", "translate"]


def test_transcriber_explains_av_and_cuda_errors():
    t = Transcriber()
    t._model = FakeWhisper(TypeError("open() got an unexpected keyword argument 'metadata_errors'"))
    with pytest.raises(RuntimeError, match='av<16'):
        t.transcribe("x.wav")
    t._model = FakeWhisper(RuntimeError("Library cublas64_12.dll is not found or cannot be loaded"))
    with pytest.raises(RuntimeError, match='device = "cpu"'):
        t.transcribe("x.wav")


def test_separate_translate_model_and_language_override():
    t = Transcriber(model_size="adalat-ai/ct2-whisper-medium-ml-rmft", translate_model="medium")
    ml, std = FakeWhisper(), FakeWhisper()
    t._models = {"adalat-ai/ct2-whisper-medium-ml-rmft": ml, "medium": std}
    out = t.transcribe("x.m4a", translate=True, language="ml")
    assert ml.tasks == ["transcribe"] and std.tasks == ["translate"]
    assert out.language == "ml"


def test_unreadable_file_gets_a_friendly_message():
    class AvError(Exception):
        pass
    AvError.__module__ = "av.error"
    t = Transcriber()
    t._model = FakeWhisper(AvError("Invalid data found when processing input"))
    with pytest.raises(RuntimeError, match="convert it to .mp3 or .wav"):
        t.transcribe("broken.amr")
