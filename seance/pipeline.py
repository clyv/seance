"""recording → Whisper transcript → Gemma memory card → archive, search index, ofrenda."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .archive import Archive, Story
from .ask import Answer, answer_question
from .card import make_card
from .config import AUDIO_EXTENSIONS, TEXT_EXTENSIONS, Config
from .llm import OllamaClient, OllamaError
from .ofrenda import write_ofrenda
from .render import write_index, write_story
from .search import SearchIndex
from .transcribe import Transcriber
from .transcript import Segment, parse_text_transcript, word_count

_STAMP_PATTERNS = [
    (re.compile(r"(20\d{2})[-_.]?(\d{2})[-_.]?(\d{2})[ _T-]+(\d{2})[-_.:]?(\d{2})[-_.:]?(\d{2})"), True),
    (re.compile(r"(20\d{2})[-_.](\d{2})[-_.](\d{2})"), False),
    # WhatsApp voice notes (PTT-20261028-WA0003.opus) and similar YYYYMMDD names
    (re.compile(r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)"), False),
]


def recorded_at(path: Path) -> datetime:
    """When a recording was made: from its file name if it has a timestamp, else its file time."""
    for pattern, has_time in _STAMP_PATTERNS:
        m = pattern.search(path.stem)
        if m:
            parts = [int(x) for x in m.groups()]
            try:
                return datetime(*parts) if has_time else datetime(*parts, 12, 0, 0)
            except ValueError:
                continue
    try:
        return datetime.fromtimestamp(path.stat().st_mtime)
    except OSError:
        return datetime.now()


@dataclass
class AddResult:
    story: Story
    embedded: bool
    words: int


class Seance:
    def __init__(self, cfg: Config, *, llm=None, transcriber=None):
        self.cfg = cfg
        self.archive = Archive(cfg)
        self._llm = llm
        self._transcriber = transcriber
        self._embedder_checked = False
        self._embedder = None

    # Lazy heavy parts --------------------------------------------------------
    @property
    def llm(self):
        if self._llm is None:
            self._llm = OllamaClient(self.cfg.ollama_url, self.cfg.model, embed_model=self.cfg.embed_model,
                                     timeout=self.cfg.timeout, num_ctx=self.cfg.num_ctx)
        return self._llm

    @property
    def transcriber(self):
        if self._transcriber is None:
            self._transcriber = Transcriber(self.cfg.whisper_model, self.cfg.whisper_device,
                                            self.cfg.whisper_compute_type, self.cfg.whisper_language,
                                            self.cfg.whisper_translate_model or None)
        return self._transcriber

    @property
    def embedder(self):
        """The Ollama client if the embedding model is pulled, else None (keyword search only)."""
        if not self._embedder_checked:
            self._embedder_checked = True
            if self.cfg.embed_model and hasattr(self.llm, "embed"):
                try:
                    if self.llm.has_model(self.cfg.embed_model):
                        self._embedder = self.llm
                except OllamaError:
                    self._embedder = None
        return self._embedder

    @property
    def index(self) -> SearchIndex:
        return SearchIndex(self.cfg.home / "index.json")

    # Adding stories ----------------------------------------------------------
    def add_file(self, path: Path, *, speaker: str, title: str | None = None,
                 recorded: datetime | None = None, translate: bool | None = None,
                 note: str = "", language: str | None = None) -> AddResult:
        spoken = language or None
        path = Path(path)
        ext = path.suffix.lower()
        if ext not in AUDIO_EXTENSIONS | TEXT_EXTENSIONS:
            raise ValueError(f"Don't know how to read {path.name} (expected audio or .txt)")
        if not path.is_file():
            raise FileNotFoundError(f"No such file: {path}")
        recorded = recorded or recorded_at(path)
        translate = self.cfg.translate if translate is None else translate

        segments: list[Segment]
        translation: list[Segment] = []
        language = spoken
        duration = t_secs = tr_secs = 0.0
        if ext in AUDIO_EXTENSIONS:
            result = self.transcriber.transcribe(path, translate=translate, language=spoken)
            segments, translation = result.segments, result.translation
            language, duration = result.language, result.duration
            t_secs, tr_secs = result.seconds, result.translate_seconds
        else:
            segments = parse_text_transcript(path.read_text(encoding="utf-8", errors="replace"))
            ends = [s.end or s.start for s in segments if (s.end or s.start) is not None]
            duration = max(ends) if ends else 0.0
        if word_count(segments) == 0:
            raise ValueError(f"No speech found in {path.name}")

        speaker = self.archive.canonical_speaker(speaker or "Unknown")
        story = Story(
            id="", title=title or "", speaker=speaker,
            recorded=recorded.isoformat(timespec="seconds"),
            added=datetime.now().isoformat(timespec="seconds"),
            segments=segments, translation=translation, source_name=path.name,
            language=language, duration=round(duration, 2),
            transcribe_seconds=round(t_secs, 2), translate_seconds=round(tr_secs, 2), note=note,
        )
        story.card = make_card(self.llm, story.working, speaker=speaker, about=title or "",
                               max_words=self.cfg.card_max_words,
                               original=segments if translation else None)
        story.title = title or story.card.title or f"A story from {speaker}"
        story.id = self.archive.new_id(recorded, story.title)
        if ext in AUDIO_EXTENSIONS:
            try:
                story.audio = self.archive.store_audio(path, story.id)
            except Exception:  # noqa: BLE001 - the story is still worth keeping without playback
                story.audio = None
        self.archive.save(story)
        self.archive.set_person(speaker)
        embedded = self._index_story(story)
        self.refresh()
        self.archive.log({
            "event": "add", "at": story.added, "story": story.id, "speaker": speaker,
            "words": word_count(story.working), "audio_seconds": story.duration,
            "transcribe_seconds": story.transcribe_seconds, "translate_seconds": story.translate_seconds,
            "gemma_seconds": story.card.model_seconds, "moments": len(story.card.moments),
            "dropped_quotes": story.card.dropped_quotes, "embedded": embedded, "model": self.cfg.model,
        })
        return AddResult(story, embedded, word_count(story.working))

    def _index_story(self, story: Story) -> bool:
        index = self.index
        try:
            embedded = index.add_story(story, self.cfg.chunk_words, self.embedder)
        except OllamaError:
            embedded = index.add_story(story, self.cfg.chunk_words, None)
        index.save()
        return embedded

    def reindex(self) -> bool:
        index = self.index
        try:
            embedded = index.rebuild(self.archive.stories(), self.cfg.chunk_words, self.embedder)
        except OllamaError:
            embedded = index.rebuild(self.archive.stories(), self.cfg.chunk_words, None)
        index.save()
        return embedded

    def refresh(self) -> None:
        """Rewrite every Markdown view and the ofrenda from the stored stories."""
        for s in self.archive.stories():
            write_story(self.archive, s)
        write_index(self.archive)
        write_ofrenda(self.archive)

    def remove(self, story: Story) -> Path:
        trash = self.archive.remove(story)
        index = self.index
        index.remove_story(story.id)
        index.save()
        self.refresh()
        return trash

    # Asking ------------------------------------------------------------------
    def ask(self, question: str, *, speaker: str | None = None, k: int | None = None) -> Answer:
        stories = {s.id: s for s in self.archive.stories()}
        hits = self.index.search(question, stories, k=k or self.cfg.top_k, speaker=speaker,
                                 embedder=self.embedder)
        ans = answer_question(self.llm, question, hits)
        self.archive.log({
            "event": "ask", "at": datetime.now().isoformat(timespec="seconds"),
            "gemma_seconds": ans.seconds, "citations": len(ans.citations), "dropped": ans.dropped,
            "found": ans.found,
        })
        return ans
