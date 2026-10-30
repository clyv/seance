"""Speech to text with faster-whisper (open Whisper weights, run locally through CTranslate2).

Unlike a voice-memo tool, an oral history needs the timestamps: every quote
Séance shows links back to the moment it was said. The Whisper model downloads
once from Hugging Face on first use; after that it runs offline.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from .transcript import Segment


@dataclass
class Transcription:
    segments: list[Segment]
    language: str | None
    duration: float          # length of the audio in seconds
    seconds: float           # how long transcription took
    translation: list[Segment] = field(default_factory=list)  # English, when asked for
    translate_seconds: float = 0.0


CUDA_HINT = (
    "Whisper tried to use the GPU but the NVIDIA CUDA libraries aren't installed.\n"
    'Set  device = "cpu"  under [whisper] in your config.toml.'
)


class Transcriber:
    """Runs one Whisper model for transcription and, optionally, another for translation.

    ``model_size`` may be a size name ("small"), a local folder, or a Hugging Face repo of a
    CTranslate2 Whisper model, such as a Malayalam fine-tune. Fine-tunes for one language
    usually lose Whisper's ability to translate, so ``translate_model`` can name a standard
    model for the English translation.
    """

    def __init__(self, model_size: str = "small", device: str = "cpu",
                 compute_type: str = "int8", language: str | None = None,
                 translate_model: str | None = None):
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.language = language or None
        self.translate_model = translate_model or model_size
        self._models: dict[str, object] = {}

    # Kept for tests and callers that set a single model directly.
    @property
    def _model(self):
        return self._models.get(self.model_size)

    @_model.setter
    def _model(self, value):
        self._models[self.model_size] = value
        if self.translate_model == self.model_size:
            self._models[self.translate_model] = value

    def _load(self, name: str | None = None):
        name = name or self.model_size
        if name in self._models:
            return self._models[name]
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError("faster-whisper is not installed. Run:  pip install faster-whisper") from exc
        try:
            model = WhisperModel(name, device=self.device, compute_type=self.compute_type)
        except (ValueError, RuntimeError) as exc:
            if "cublas" in str(exc).lower() or "cuda" in str(exc).lower():
                raise RuntimeError(CUDA_HINT) from exc
            model = WhisperModel(name, device=self.device, compute_type="default")
        self._models[name] = model
        return model

    def _run(self, path: Path, task: str, language: str | None, model_name: str | None = None):
        model = self._load(model_name)
        started = time.perf_counter()
        try:
            segs, info = model.transcribe(
                str(path), language=language, task=task, vad_filter=True, beam_size=5,
            )
            segments = [Segment(text=s.text.strip(), start=round(float(s.start), 2), end=round(float(s.end), 2))
                        for s in segs if s.text.strip()]
        except TypeError as exc:
            if "metadata_errors" in str(exc):
                raise RuntimeError(
                    "Your PyAV version is too new for faster-whisper. Fix it with:\n"
                    '    pip install "av<16"'
                ) from exc
            raise
        except RuntimeError as exc:
            if "cublas" in str(exc).lower():
                raise RuntimeError(CUDA_HINT) from exc
            raise
        except Exception as exc:  # noqa: BLE001 - PyAV raises its own error types for unreadable files
            if type(exc).__module__.startswith("av"):
                raise RuntimeError(
                    f"Couldn't read the audio in {Path(path).name} ({exc}). If it plays on your computer, "
                    "convert it to .mp3 or .wav (any audio converter works) and add that instead."
                ) from exc
            raise
        return segments, info, time.perf_counter() - started

    def transcribe(self, path: Path, *, translate: bool = False, language: str | None = None) -> Transcription:
        lang = language or self.language
        segments, info, seconds = self._run(path, "transcribe", lang)
        detected = lang or getattr(info, "language", None)
        result = Transcription(
            segments=segments,
            language=detected,
            duration=float(getattr(info, "duration", 0.0) or 0.0),
            seconds=seconds,
        )
        if translate and detected and detected != "en":
            result.translation, _, result.translate_seconds = self._run(
                path, "translate", detected, self.translate_model)
        return result
