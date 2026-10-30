"""Recording from the microphone and playing a moment back.

Both are optional extras (pip install sounddevice numpy). On the go, record on
your phone and use `seance add` instead.
"""

from __future__ import annotations

import threading
import time
import wave
from pathlib import Path

SAMPLE_RATE = 16000  # Whisper works at 16 kHz mono, so record that directly.

INSTALL_HINT = (
    "Recording and playback need two extra packages:\n"
    "    pip install sounddevice numpy"
)


def write_wav(path: Path, pcm16: bytes, samplerate: int = SAMPLE_RATE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(samplerate)
        wf.writeframes(pcm16)


def _import_audio():
    try:
        import numpy as np
        import sounddevice as sd
    except ImportError as exc:
        raise RuntimeError(INSTALL_HINT) from exc
    return np, sd


def record_wav(path: Path, *, seconds: float | None = None, samplerate: int = SAMPLE_RATE,
               on_tick=None) -> float:
    """Record until Enter is pressed (or for ``seconds``). Returns the length in seconds."""
    np, sd = _import_audio()
    chunks = []
    stop = threading.Event()

    def callback(indata, frames, time_info, status):  # noqa: ARG001
        chunks.append(indata.copy())

    started = time.monotonic()
    with sd.InputStream(samplerate=samplerate, channels=1, dtype="int16", callback=callback):
        if seconds:
            end = started + seconds
            while time.monotonic() < end:
                time.sleep(0.25)
                if on_tick:
                    on_tick(time.monotonic() - started)
        else:
            waiter = threading.Thread(target=lambda: (input(), stop.set()), daemon=True)
            waiter.start()
            while not stop.is_set():
                time.sleep(0.25)
                if on_tick:
                    on_tick(time.monotonic() - started)
    audio = np.concatenate(chunks) if chunks else np.zeros((0, 1), dtype="int16")
    write_wav(path, audio.tobytes(), samplerate)
    return len(audio) / samplerate


def to_listening_wav(source: Path, dest: Path) -> float:
    """Decode any recording FFmpeg can read into a 16 kHz mono WAV every browser can play.

    Used for formats browsers can't play (.amr, .3gp, .wma, video files...), so the
    ofrenda's ▶ buttons work. 16 kHz mono is plenty for speech: about 2 MB a minute.
    Returns the length in seconds.
    """
    try:
        import numpy as np
        from faster_whisper.audio import decode_audio
    except ImportError as exc:
        raise RuntimeError("faster-whisper is needed to convert recordings.") from exc
    audio = decode_audio(str(source), sampling_rate=SAMPLE_RATE)
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2").tobytes()
    write_wav(dest, pcm, SAMPLE_RATE)
    return len(audio) / SAMPLE_RATE


def clip_bounds(start: float | None, end: float | None, *, pad: float = 0.4,
                max_len: float = 30.0) -> tuple[float, float]:
    s = max(0.0, (start or 0.0) - pad)
    e = (end if end is not None else s + 12.0) + pad
    return s, min(e, s + max_len)


def play_moment(path: Path, start: float | None, end: float | None) -> float:
    """Play [start, end] of a recording through the speakers. Returns seconds played."""
    np, sd = _import_audio()
    try:
        from faster_whisper.audio import decode_audio
    except ImportError as exc:
        raise RuntimeError("faster-whisper is needed to decode the recording.") from exc
    audio = decode_audio(str(path), sampling_rate=SAMPLE_RATE)
    s, e = clip_bounds(start, end)
    clip = audio[int(s * SAMPLE_RATE):int(e * SAMPLE_RATE)]
    if len(clip) == 0:
        return 0.0
    sd.play(np.asarray(clip, dtype="float32"), SAMPLE_RATE)
    sd.wait()
    return len(clip) / SAMPLE_RATE
