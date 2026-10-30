"""Finding the right passages for a question.

Transcripts are cut into short, overlapping passages. Search is keyword (BM25,
pure Python) and, if you've pulled it, semantic search with EmbeddingGemma
through Ollama, combined with reciprocal-rank fusion. Keyword search alone
works fine; embeddings help when the question uses different words from the
speaker ("the house" vs "our home in Kottayam").
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol

from .archive import Story, atomic_write_text
from .transcript import STOPWORDS, Segment, norm


class Embedder(Protocol):
    embed_model: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...


@dataclass
class Chunk:
    story_id: str
    idx: int
    text: str
    start: float | None
    end: float | None
    seg_first: int
    seg_last: int
    vec: list[float] | None = field(default=None, repr=False)

    @property
    def key(self) -> str:
        return f"{self.story_id}#{self.idx}"


def chunk_segments(story_id: str, segments: list[Segment], chunk_words: int = 110) -> list[Chunk]:
    """Group consecutive segments into ~chunk_words passages, overlapping by one segment."""
    chunks: list[Chunk] = []
    i = 0
    n = len(segments)
    while i < n:
        j, words = i, 0
        while j < n and (words == 0 or words + len(segments[j].text.split()) <= chunk_words):
            words += len(segments[j].text.split())
            j += 1
        part = segments[i:j]
        chunks.append(Chunk(
            story_id=story_id, idx=len(chunks), text=" ".join(s.text.strip() for s in part),
            start=part[0].start, end=part[-1].end, seg_first=i, seg_last=j - 1,
        ))
        if j >= n:
            break
        i = j - 1 if j - 1 > i else j   # overlap one segment so no moment is split in two
    return chunks


def tokenize(text: str) -> list[str]:
    out = []
    for w in text.split():
        t = norm(w)
        if not t or t in STOPWORDS:
            continue
        if len(t) > 4 and t.endswith("s") and not t.endswith("ss"):
            t = t[:-1]
        out.append(t)
    return out


def chunk_headings(story: Story, chunk: Chunk) -> str:
    """Headings of the memory-card moments that fall inside this passage.

    The headings are in Gemma's words ("The 1961 flood"), the passage in the
    speaker's ("the water came right up to the verandah steps"), so searching
    both lets a question find a passage that never uses its words.
    """
    out = []
    for m in story.card.moments:
        if m.start is None or chunk.start is None:
            continue
        end = chunk.end if chunk.end is not None else chunk.start + 1e9
        if chunk.start <= m.start < end:
            out.append(m.heading)
    return ". ".join(out)


def embed_text(story: Story, chunk: Chunk) -> str:
    heads = chunk_headings(story, chunk)
    return f"{story.speaker}: " + (f"{heads}. " if heads else "") + chunk.text


class BM25:
    def __init__(self, docs: list[list[str]], k1: float = 1.5, b: float = 0.75):
        self.docs = docs
        self.k1, self.b = k1, b
        self.avgdl = (sum(len(d) for d in docs) / len(docs)) if docs else 0.0
        self.df: dict[str, int] = {}
        for d in docs:
            for t in set(d):
                self.df[t] = self.df.get(t, 0) + 1
        self.tf = [self._counts(d) for d in docs]

    @staticmethod
    def _counts(doc: list[str]) -> dict[str, int]:
        c: dict[str, int] = {}
        for t in doc:
            c[t] = c.get(t, 0) + 1
        return c

    def scores(self, query: list[str]) -> list[float]:
        n = len(self.docs)
        out = []
        for doc, tf in zip(self.docs, self.tf):
            s = 0.0
            for t in set(query):
                if t not in tf:
                    continue
                idf = math.log(1 + (n - self.df[t] + 0.5) / (self.df[t] + 0.5))
                f = tf[t]
                s += idf * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * len(doc) / (self.avgdl or 1)))
            out.append(s)
        return out


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


@dataclass
class Hit:
    chunk: Chunk
    story: Story
    score: float


class SearchIndex:
    """Passages for every story, saved to index.json next to the stories."""

    def __init__(self, path: Path):
        self.path = path
        self.chunks: list[Chunk] = []
        self.embed_model: str | None = None
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                self.embed_model = data.get("embed_model")
                self.chunks = [Chunk(**c) for c in data.get("chunks", [])]
            except (ValueError, TypeError):
                self.chunks = []

    def save(self) -> None:
        data = {"version": 1, "embed_model": self.embed_model,
                "chunks": [asdict(c) for c in self.chunks]}
        atomic_write_text(self.path, json.dumps(data, ensure_ascii=False))

    @property
    def has_vectors(self) -> bool:
        return bool(self.chunks) and all(c.vec for c in self.chunks)

    def remove_story(self, story_id: str) -> None:
        self.chunks = [c for c in self.chunks if c.story_id != story_id]

    def add_story(self, story: Story, chunk_words: int, embedder: Embedder | None = None) -> bool:
        """(Re)index one story. Returns True if embeddings were stored."""
        self.remove_story(story.id)
        new = chunk_segments(story.id, story.working, chunk_words)
        embedded = False
        if embedder is not None and new:
            if self.embed_model in (None, embedder.embed_model) and (not self.chunks or self.has_vectors):
                vecs = embedder.embed([embed_text(story, c) for c in new])
                for c, v in zip(new, vecs):
                    c.vec = v
                self.embed_model = embedder.embed_model
                embedded = True
        if not embedded:
            # Mixing embedded and plain passages would skew results; fall back to keywords everywhere.
            for c in self.chunks:
                c.vec = None
            self.embed_model = None
        self.chunks.extend(new)
        return embedded

    def rebuild(self, stories: list[Story], chunk_words: int, embedder: Embedder | None = None) -> bool:
        self.chunks = []
        self.embed_model = None
        all_new: list[tuple[Story, Chunk]] = []
        for s in stories:
            for c in chunk_segments(s.id, s.working, chunk_words):
                all_new.append((s, c))
        embedded = False
        if embedder is not None and all_new:
            vecs = embedder.embed([embed_text(s, c) for s, c in all_new])
            for (_, c), v in zip(all_new, vecs):
                c.vec = v
            self.embed_model = embedder.embed_model
            embedded = True
        self.chunks = [c for _, c in all_new]
        return embedded

    def search(self, query: str, stories: dict[str, Story], *, k: int = 6,
               speaker: str | None = None, embedder: Embedder | None = None) -> list[Hit]:
        pool = [c for c in self.chunks if c.story_id in stories]
        if speaker:
            pool = [c for c in pool if stories[c.story_id].speaker.casefold() == speaker.casefold()]
        if not pool:
            return []
        docs = []
        for c in pool:
            s = stories[c.story_id]
            docs.append(tokenize(c.text) + tokenize(s.speaker) + tokenize(s.title) + tokenize(chunk_headings(s, c)))
        q = tokenize(query)
        bm = BM25(docs).scores(q) if q else [0.0] * len(pool)
        ranked_lists = [sorted(range(len(pool)), key=lambda i: -bm[i])]
        relevant = {i for i, s in enumerate(bm) if s > 0}

        if embedder is not None and self.has_vectors and self.embed_model == embedder.embed_model:
            try:
                qv = embedder.embed([query])[0]
            except Exception:  # noqa: BLE001 - search still works on keywords alone
                qv = None
            if qv is not None:
                cos = [cosine(qv, c.vec or []) for c in pool]
                ranked_lists.append(sorted(range(len(pool)), key=lambda i: -cos[i]))
                best = max(cos) if cos else 0.0
                relevant |= {i for i, v in enumerate(cos) if v >= max(0.3, best - 0.15)}

        fused: dict[int, float] = {}
        for ranking in ranked_lists:
            for rank, i in enumerate(ranking):
                fused[i] = fused.get(i, 0.0) + 1.0 / (60 + rank)
        order = sorted((i for i in fused if i in relevant), key=lambda i: -fused[i])
        return [Hit(pool[i], stories[pool[i].story_id], round(fused[i], 5)) for i in order[:k]]
