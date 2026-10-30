"""Timestamped transcripts, and finding a quote inside one.

Gemma is never trusted to quote anyone. When it picks a quote, `find_quote`
looks for those words in the real transcript and returns the *transcript's*
wording with its timestamp. A quote that can't be found is dropped. That is the
rule the whole project rests on: Séance never puts words in anyone's mouth.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher


@dataclass
class Segment:
    text: str
    start: float | None = None
    end: float | None = None

    def to_dict(self) -> dict:
        return {"text": self.text, "start": self.start, "end": self.end}

    @classmethod
    def from_dict(cls, d: dict) -> "Segment":
        return cls(text=str(d.get("text", "")), start=d.get("start"), end=d.get("end"))


# Timestamps ---------------------------------------------------------------

def fmt_ts(seconds: float | None) -> str:
    if seconds is None:
        return ""
    total = int(round(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


_TS = r"(?:(\d{1,2}):)?(\d{1,2}):(\d{2})(?:[.,]\d+)?"
_BRACKET_LINE = re.compile(r"^\s*\[([\d:.,]+)\](?:\s*[-–—]\s*\[([\d:.,]+)\])?\s*(.*)$")
_PLAIN_LINE = re.compile(r"^\s*(\d{1,2}:\d{2}(?::\d{2})?)\s*[-–—:]?\s+(.*)$")


def parse_ts(text: str) -> float | None:
    m = re.fullmatch(r"\s*" + _TS + r"\s*", text)
    if not m:
        return None
    h, mi, s = m.groups()
    return float(int(h or 0) * 3600 + int(mi) * 60 + int(s))


def _split_ts_line(line: str) -> tuple[float, float | None, str] | None:
    m = _BRACKET_LINE.match(line)
    if m:
        start = parse_ts(m.group(1))
        if start is not None:
            end = parse_ts(m.group(2)) if m.group(2) else None
            return start, end, m.group(3).strip()
    m = _PLAIN_LINE.match(line)
    if m:
        start = parse_ts(m.group(1))
        if start is not None:
            return start, None, m.group(2).strip()
    return None


def parse_text_transcript(text: str) -> list[Segment]:
    """Turn a .txt/.md transcript into segments.

    Lines starting with a timestamp like ``[03:12]`` or ``[1:02:03]`` start a new
    timestamped segment (this is the format Séance writes, so its own transcripts
    re-import cleanly). Without timestamps, each paragraph becomes a segment.
    """
    lines = [ln.rstrip() for ln in text.replace("\r\n", "\n").split("\n")]
    content = [ln for ln in lines if ln.strip() and not ln.lstrip().startswith("#")]
    has_ts = any(_split_ts_line(ln) for ln in content)
    segments: list[Segment] = []
    if has_ts:
        for ln in content:
            parsed = _split_ts_line(ln)
            if parsed:
                start, end, body = parsed
                segments.append(Segment(text=body, start=start, end=end))
            elif segments:
                segments[-1].text = (segments[-1].text + " " + ln.strip()).strip()
            else:
                segments.append(Segment(text=ln.strip()))
        for a, b in zip(segments, segments[1:]):
            if a.end is None and b.start is not None:
                a.end = b.start
        return [s for s in segments if s.text]
    paragraph: list[str] = []
    for ln in lines + [""]:
        if ln.strip() and not ln.lstrip().startswith("#"):
            paragraph.append(ln.strip())
        elif paragraph:
            segments.append(Segment(text=" ".join(paragraph)))
            paragraph = []
    return segments


def full_text(segments: list[Segment]) -> str:
    return " ".join(s.text.strip() for s in segments if s.text.strip())


def word_count(segments: list[Segment]) -> int:
    return sum(len(s.text.split()) for s in segments)


def overlapping_text(segments: list[Segment], start: float | None, end: float | None) -> str:
    """Text of the segments that overlap [start, end] (used to show the original language)."""
    if start is None or not segments:
        return ""
    end = start + 1.0 if end is None else end
    parts = [s.text for s in segments
             if s.start is not None and (s.end if s.end is not None else s.start + 1) > start and s.start < end]
    return " ".join(p.strip() for p in parts)


# Quote matching -------------------------------------------------------------

_WORD = re.compile(r"[\w']+", re.UNICODE)
STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "of", "to", "in", "on", "at", "for", "with", "is", "was",
    "were", "be", "been", "it", "its", "that", "this", "i", "we", "you", "he", "she", "they", "my",
    "our", "your", "his", "her", "their", "me", "us", "him", "them", "so", "then", "there", "as",
    "by", "from", "had", "have", "has", "do", "did", "not", "no", "yes", "um", "uh", "like",
}


def norm(word: str) -> str:
    """Lower-case a word and keep only letters, combining marks and digits.

    Keeping marks (category M) matters for scripts like Malayalam, where vowel
    signs are marks: without them മാവ് (mango tree) and മവ would look the same.
    """
    return "".join(ch for ch in word.lower() if unicodedata.category(ch)[0] in "LMN")


@dataclass
class Word:
    text: str
    norm: str
    seg: int


def words_of(segments: list[Segment]) -> list[Word]:
    out: list[Word] = []
    for i, seg in enumerate(segments):
        for raw in seg.text.split():
            n = norm(raw)
            if n:
                out.append(Word(raw, n, i))
    return out


@dataclass
class QuoteMatch:
    text: str           # the transcript's own wording
    score: float        # share of the quote's words found, in order
    start: float | None
    end: float | None
    seg_first: int
    seg_last: int


def _tokens(text: str) -> list[str]:
    return [n for n in (norm(w) for w in text.split()) if n]


def _best_window(q: list[str], words: list[Word]) -> tuple[float, int, int]:
    """Best in-order match of q inside words. Returns (score, first_idx, last_idx)."""
    if not q or not words:
        return 0.0, -1, -1
    norms = [w.norm for w in words]
    key = {t for t in q if t not in STOPWORDS} or set(q)
    span = len(q) + max(2, len(q) // 3)
    starts: set[int] = set()
    for i, n in enumerate(norms):
        if n in key:
            for back in range(0, min(len(q), 6)):
                starts.add(max(0, i - back))
    best = (0.0, -1, -1)
    for s in sorted(starts):
        window = norms[s:s + span]
        sm = SequenceMatcher(None, q, window, autojunk=False)
        blocks = [b for b in sm.get_matching_blocks() if b.size]
        matched = sum(b.size for b in blocks)
        score = matched / len(q)
        if score > best[0] + 1e-9:
            first = s + blocks[0].b
            last = s + blocks[-1].b + blocks[-1].size - 1
            best = (score, first, last)
            if score >= 0.999:
                break
    return best


def find_quote(quote: str, segments: list[Segment], *, min_score: float = 0.6,
               words: list[Word] | None = None) -> QuoteMatch | None:
    """Locate a (possibly slightly misquoted) quote in the transcript.

    Returns the matching span in the transcript's own words, or None when fewer
    than ``min_score`` of the quote's words appear there in order.
    """
    words = words if words is not None else words_of(segments)
    q = _tokens(quote)
    if not q or not words:
        return None
    candidates = [q]
    # Models sometimes stitch two bits together with an ellipsis; try the longest piece too.
    pieces = [p for p in re.split(r"\.\.\.|…", quote) if len(_tokens(p)) >= 4]
    if len(pieces) > 1:
        candidates.append(_tokens(max(pieces, key=lambda p: len(_tokens(p)))))
    best: tuple[float, int, int] = (0.0, -1, -1)
    for cand in candidates:
        threshold = 1.0 if len(cand) < 4 else min_score
        score, first, last = _best_window(cand, words)
        if score >= threshold and score > best[0]:
            best = (score, first, last)
    score, first, last = best
    if first < 0:
        return None
    text = " ".join(w.text for w in words[first:last + 1]).strip()
    text = text.strip(" ,;:-–—\"“”'")
    seg_first, seg_last = words[first].seg, words[last].seg
    return QuoteMatch(
        text=text,
        score=round(score, 3),
        start=segments[seg_first].start,
        end=segments[seg_last].end,
        seg_first=seg_first,
        seg_last=seg_last,
    )
