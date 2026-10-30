"""The archive on disk: one JSON file per story, plus people.json and a log.

Everything is plain files in one folder you own, so the archive outlives this
program: the Markdown transcripts and the ofrenda page open without Séance.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .card import Card
from .config import Config
from .transcript import Segment


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=path.suffix)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def slugify(text: str, limit: int = 48) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    return (text[:limit].rstrip("-")) or "story"


@dataclass
class Story:
    id: str
    title: str
    speaker: str
    recorded: str                       # ISO datetime the recording was made
    added: str                          # ISO datetime it entered the archive
    segments: list[Segment] = field(default_factory=list)
    translation: list[Segment] = field(default_factory=list)
    card: Card = field(default_factory=Card)
    audio: str | None = None            # path relative to the archive home, e.g. recordings/x.m4a
    source_name: str = ""
    language: str | None = None
    duration: float = 0.0
    transcribe_seconds: float = 0.0
    translate_seconds: float = 0.0
    note: str = ""

    @property
    def working(self) -> list[Segment]:
        """The segments everything reads: the English translation if there is one."""
        return self.translation or self.segments

    @property
    def recorded_date(self) -> str:
        return self.recorded[:10]

    def to_dict(self) -> dict:
        return {
            "id": self.id, "title": self.title, "speaker": self.speaker,
            "recorded": self.recorded, "added": self.added, "audio": self.audio,
            "source_name": self.source_name, "language": self.language,
            "duration": self.duration, "transcribe_seconds": self.transcribe_seconds,
            "translate_seconds": self.translate_seconds, "note": self.note,
            "card": self.card.to_dict(),
            "segments": [s.to_dict() for s in self.segments],
            "translation": [s.to_dict() for s in self.translation],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Story":
        return cls(
            id=d["id"], title=d.get("title", ""), speaker=d.get("speaker", ""),
            recorded=d.get("recorded", ""), added=d.get("added", ""),
            segments=[Segment.from_dict(s) for s in d.get("segments", [])],
            translation=[Segment.from_dict(s) for s in d.get("translation", [])],
            card=Card.from_dict(d.get("card", {})),
            audio=d.get("audio"), source_name=d.get("source_name", ""),
            language=d.get("language"), duration=float(d.get("duration") or 0.0),
            transcribe_seconds=float(d.get("transcribe_seconds") or 0.0),
            translate_seconds=float(d.get("translate_seconds") or 0.0),
            note=d.get("note", ""),
        )


class Archive:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.home = cfg.home

    # Stories -----------------------------------------------------------------
    def story_path(self, story_id: str) -> Path:
        return self.cfg.stories_dir / f"{story_id}.json"

    def stories(self) -> list[Story]:
        out = []
        if self.cfg.stories_dir.is_dir():
            for p in sorted(self.cfg.stories_dir.glob("*.json")):
                try:
                    out.append(Story.from_dict(json.loads(p.read_text(encoding="utf-8"))))
                except (OSError, ValueError, KeyError):
                    continue
        out.sort(key=lambda s: (s.recorded, s.id))
        return out

    def save(self, story: Story) -> Path:
        path = self.story_path(story.id)
        atomic_write_text(path, json.dumps(story.to_dict(), ensure_ascii=False, indent=1))
        return path

    def new_id(self, recorded: datetime, title: str) -> str:
        base = f"{recorded:%Y-%m-%d}-{slugify(title)}"
        candidate, n = base, 2
        while self.story_path(candidate).exists():
            candidate = f"{base}-{n}"
            n += 1
        return candidate

    def find(self, key: str) -> Story | None:
        """Look a story up by id, id prefix, or (part of) its title."""
        key_l = key.casefold().strip()
        stories = self.stories()
        for s in stories:
            if s.id == key:
                return s
        for pool in (
            [s for s in stories if s.id.startswith(key)],
            [s for s in stories if s.title.casefold() == key_l],
            [s for s in stories if key_l in s.title.casefold() or key_l in s.id],
        ):
            if len(pool) == 1:
                return pool[0]
            if len(pool) > 1:
                raise LookupError("More than one story matches '%s': %s" % (key, ", ".join(s.id for s in pool)))
        return None

    def remove(self, story: Story) -> Path:
        """Move a story (and its audio) into trash/ rather than deleting it."""
        trash = self.home / "trash" / story.id
        trash.mkdir(parents=True, exist_ok=True)
        for p in (self.story_path(story.id), self.cfg.stories_dir / f"{story.id}.md"):
            if p.exists():
                shutil.move(str(p), str(trash / p.name))
        if story.audio and not any(s.audio == story.audio for s in self.stories()):
            audio = self.home / story.audio
            if audio.exists():
                shutil.move(str(audio), str(trash / audio.name))
        return trash

    def store_audio(self, source: Path, story_id: str, converter=None) -> str:
        """Put a playable copy of the recording in the archive for the ofrenda page.

        Formats every browser plays (.mp3, .m4a, .wav, .ogg/.opus, .flac) are copied as they
        are. Anything else (.amr, .3gp, .wma, .aiff, video files) becomes a 16 kHz WAV
        listening copy. Your original file is never changed.
        """
        from .config import PLAYABLE_EXTENSIONS
        self.cfg.recordings_dir.mkdir(parents=True, exist_ok=True)
        ext = source.suffix.lower()
        if ext in PLAYABLE_EXTENSIONS:
            dest = self.cfg.recordings_dir / f"{story_id}{ext}"
            if source.resolve() != dest.resolve():
                shutil.copy2(source, dest)
        else:
            dest = self.cfg.recordings_dir / f"{story_id}.wav"
            if converter is None:
                from .audio import to_listening_wav as converter
            converter(source, dest)
        return dest.relative_to(self.home).as_posix()

    # People ------------------------------------------------------------------
    @property
    def people_path(self) -> Path:
        return self.home / "people.json"

    def people(self) -> dict[str, dict]:
        if not self.people_path.exists():
            return {}
        try:
            data = json.loads(self.people_path.read_text(encoding="utf-8"))
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    def canonical_speaker(self, name: str) -> str:
        """Match a speaker name case-insensitively to one already in the archive."""
        name = name.strip()
        known = list(self.people()) + [s.speaker for s in self.stories()]
        for k in known:
            if k.casefold() == name.casefold():
                return k
        return name

    def set_person(self, name: str, **fields: str) -> dict:
        people = self.people()
        name = self.canonical_speaker(name)
        entry = people.get(name, {})
        for k, v in fields.items():
            if v is not None:
                entry[k] = v
        people[name] = entry
        atomic_write_text(self.people_path, json.dumps(people, ensure_ascii=False, indent=2))
        return entry

    def speakers(self) -> list[tuple[str, int]]:
        counts: dict[str, int] = {}
        for s in self.stories():
            counts[s.speaker] = counts.get(s.speaker, 0) + 1
        for name in self.people():
            counts.setdefault(name, 0)
        return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].casefold()))

    # Log ---------------------------------------------------------------------
    @property
    def log_path(self) -> Path:
        return self.home / "log.jsonl"

    def log(self, entry: dict) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def read_log(self) -> list[dict]:
        if not self.log_path.exists():
            return []
        out = []
        for line in self.log_path.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
        return out
