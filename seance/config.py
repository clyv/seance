"""Configuration: where the archive lives and which local models to use."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised on Python 3.10 only
    import tomli as tomllib

# Anything FFmpeg (through PyAV) can decode works; these are the extensions Séance picks up.
AUDIO_EXTENSIONS = {
    # audio: phone recorders, WhatsApp/Telegram voice notes, call recorders, old dictaphones
    ".m4a", ".mp3", ".wav", ".ogg", ".oga", ".opus", ".flac", ".aac", ".amr", ".3gp", ".3ga",
    ".wma", ".aif", ".aiff", ".caf", ".m4b", ".mka",
    # video: the sound track of a family video is used
    ".mp4", ".m4v", ".mov", ".mkv", ".avi", ".webm", ".wmv",
}
# Formats every major browser can play, so the ofrenda's ▶ buttons work on them as they are.
# Everything else gets a small WAV listening copy when it's added.
PLAYABLE_EXTENSIONS = {".mp3", ".m4a", ".aac", ".wav", ".ogg", ".oga", ".opus", ".flac"}
TEXT_EXTENSIONS = {".txt", ".md"}

EXAMPLE_CONFIG = """\
# Séance configuration
# Paths accept ~ and environment variables. On Windows, forward slashes work fine,
# e.g. "C:/Users/you/Documents/Family Stories".

# Where the archive lives: recordings, transcripts, memory cards and the ofrenda page
home = "{home}"

[llm]
url = "http://localhost:11434"   # local Ollama server
model = "gemma4:e4b"             # any Gemma tag you have pulled, e.g. gemma4:e2b
embed_model = "embeddinggemma"   # optional; used for search if pulled, otherwise keyword search
num_ctx = 8192                   # context window passed to Ollama
timeout = 600                    # seconds

[whisper]
model = "small"        # tiny | base | small | medium | large-v3 | turbo, or a Hugging Face repo of a
                       # CTranslate2 Whisper model, e.g. a Malayalam fine-tune (see the README)
translate_model = ""   # model for --translate; empty = same as model. Set to "medium" if `model`
                       # is a single-language fine-tune, since those usually can't translate
device = "cpu"         # cpu | cuda (cuda needs NVIDIA CUDA 12 libraries installed)
compute_type = "int8"  # int8 is fast on CPU; float16 is a good choice on an NVIDIA GPU
language = ""          # e.g. "ml" for Malayalam, "hi" for Hindi; empty = auto-detect
translate = false      # also make an English translation of non-English recordings

[archive]
chunk_words = 110      # size of the transcript passages used for search
card_max_words = 2800  # longer transcripts are summarised in parts, then merged
top_k = 6              # passages Gemma reads when answering a question
"""


@dataclass
class Config:
    home: Path = field(default_factory=lambda: default_home())
    ollama_url: str = "http://localhost:11434"
    model: str = "gemma4:e4b"
    embed_model: str = "embeddinggemma"
    num_ctx: int = 8192
    timeout: float = 600.0
    whisper_model: str = "small"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    whisper_language: str = ""
    whisper_translate_model: str = ""
    translate: bool = False
    chunk_words: int = 110
    card_max_words: int = 2800
    top_k: int = 6
    source: Path | None = None  # the config file this was loaded from, if any

    @property
    def recordings_dir(self) -> Path:
        return self.home / "recordings"

    @property
    def stories_dir(self) -> Path:
        return self.home / "stories"

    @property
    def photos_dir(self) -> Path:
        return self.home / "photos"

    @property
    def inbox(self) -> Path:
        return self.home / "inbox"

    @property
    def config_path(self) -> Path:
        return self.home / "config.toml"

    def ensure_dirs(self) -> None:
        for d in (self.home, self.recordings_dir, self.stories_dir, self.photos_dir, self.inbox):
            d.mkdir(parents=True, exist_ok=True)


def default_home() -> Path:
    env = os.environ.get("SEANCE_HOME")
    if env:
        return Path(os.path.expandvars(env)).expanduser()
    return Path.home() / "Seance"


def _path(value: str) -> Path:
    return Path(os.path.expandvars(value)).expanduser()


def find_config_file(explicit: str | None = None) -> Path | None:
    """--config, then $SEANCE_CONFIG, then ./seance.toml, then <home>/config.toml."""
    candidates: list[Path] = []
    if explicit:
        return _path(explicit)
    env = os.environ.get("SEANCE_CONFIG")
    if env:
        candidates.append(_path(env))
    candidates.append(Path.cwd() / "seance.toml")
    candidates.append(default_home() / "config.toml")
    for c in candidates:
        if c.is_file():
            return c
    return None


def load_config(explicit: str | None = None) -> Config:
    cfg = Config()
    path = find_config_file(explicit)
    if path is None:
        return cfg
    if not path.is_file():
        raise FileNotFoundError(f"Config file not found: {path}")
    with path.open("rb") as fh:
        data = tomllib.load(fh)
    cfg.source = path
    if "home" in data:
        cfg.home = _path(str(data["home"]))
    llm = data.get("llm", {})
    cfg.ollama_url = str(llm.get("url", cfg.ollama_url))
    cfg.model = str(llm.get("model", cfg.model))
    cfg.embed_model = str(llm.get("embed_model", cfg.embed_model))
    cfg.num_ctx = int(llm.get("num_ctx", cfg.num_ctx))
    cfg.timeout = float(llm.get("timeout", cfg.timeout))
    whisper = data.get("whisper", {})
    cfg.whisper_model = str(whisper.get("model", cfg.whisper_model))
    cfg.whisper_device = str(whisper.get("device", cfg.whisper_device))
    cfg.whisper_compute_type = str(whisper.get("compute_type", cfg.whisper_compute_type))
    cfg.whisper_language = str(whisper.get("language", cfg.whisper_language))
    cfg.whisper_translate_model = str(whisper.get("translate_model", cfg.whisper_translate_model))
    cfg.translate = bool(whisper.get("translate", cfg.translate))
    archive = data.get("archive", {})
    cfg.chunk_words = int(archive.get("chunk_words", cfg.chunk_words))
    cfg.card_max_words = int(archive.get("card_max_words", cfg.card_max_words))
    cfg.top_k = int(archive.get("top_k", cfg.top_k))
    return cfg


def write_example_config(home: Path) -> Path:
    home.mkdir(parents=True, exist_ok=True)
    path = home / "config.toml"
    path.write_text(EXAMPLE_CONFIG.format(home=home.as_posix()), encoding="utf-8")
    return path
