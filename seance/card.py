"""Memory cards: Gemma reads a recording's transcript and writes a structured card.

Gemma chooses what matters (people, places, years, the most vivid moments);
code checks every quote against the transcript before it's kept.
"""

from __future__ import annotations

import re
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

from .transcript import Segment, find_quote, full_text, overlapping_text, words_of


class ChatLLM(Protocol):
    def chat_json(self, prompt: str, schema: dict) -> Any: ...


CARD_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "summary": {"type": "string"},
        "people": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"name": {"type": "string"}, "relation": {"type": "string"}},
                "required": ["name", "relation"],
            },
        },
        "places": {"type": "array", "items": {"type": "string"}},
        "years": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"when": {"type": "string"}, "what": {"type": "string"}},
                "required": ["when", "what"],
            },
        },
        "moments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"heading": {"type": "string"}, "quote": {"type": "string"}},
                "required": ["heading", "quote"],
            },
        },
        "themes": {"type": "array", "items": {"type": "string"}},
        "follow_up_questions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title", "summary", "people", "places", "years", "moments", "themes", "follow_up_questions"],
}

MERGE_SCHEMA: dict = {
    "type": "object",
    "properties": {"title": {"type": "string"}, "summary": {"type": "string"}},
    "required": ["title", "summary"],
}

CARD_PROMPT = """You are helping a family keep an archive of their elders' stories.
Below is a transcript of {speaker} talking{about}.{part_note}

Write a memory card as JSON with these fields:
- title: a short, warm title for the story, at most 8 words, using the speaker's own terms.
- summary: 2-3 plain sentences in the third person. Only what {speaker} actually said.
- people: people mentioned, with their relation to {speaker} if it is said (otherwise "").
- places: places mentioned (towns, houses, schools, countries, streets).
- years: points in time mentioned (a year, a decade, or an age like "when I was ten") and what happened then.
- moments: the {n_moments} most vivid moments. For each, a short heading and a quote copied EXACTLY,
  word for word, from the transcript (10 to 40 words). Do not fix grammar. Do not paraphrase.
- themes: 2 to 5 themes, one or two words each.
- follow_up_questions: 3 questions a grandchild could ask next time, about things {speaker}
  mentioned but didn't explain.

Rules:
- Write the card in English. If the transcript is in another language (Malayalam, Hindi...),
  copy each quote in that language exactly as written in the transcript; do not translate quotes.
- Use only what is in the transcript. Never invent names, dates, places or relations.
- If something isn't mentioned, leave that list empty.
- The transcript may contain the interviewer's voice too; the card is about {speaker}'s memories.

Transcript:
\"\"\"
{transcript}
\"\"\"
"""

MERGE_PROMPT = """These are summaries of consecutive parts of one recording of {speaker}.
Write one title (at most 8 words, warm, in the speaker's terms) and one summary
(3 plain sentences, third person) for the whole recording. Use only what is below.

{parts}
"""

_YEAR = re.compile(r"\b(1[6-9]\d\d|20\d\d)(?:'?s)?\b")


@dataclass
class Moment:
    heading: str
    quote: str                  # the transcript's own words, never the model's
    start: float | None = None
    end: float | None = None
    score: float = 1.0
    original: str = ""          # original-language words, when the card was made from a translation


@dataclass
class Card:
    title: str = ""
    summary: str = ""
    people: list[dict] = field(default_factory=list)
    places: list[str] = field(default_factory=list)
    years: list[dict] = field(default_factory=list)
    moments: list[Moment] = field(default_factory=list)
    themes: list[str] = field(default_factory=list)
    follow_up_questions: list[str] = field(default_factory=list)
    dropped_quotes: int = 0     # quotes Gemma gave that weren't in the transcript
    model_seconds: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Card":
        d = dict(d or {})
        moments = [Moment(**{k: v for k, v in m.items() if k in Moment.__dataclass_fields__})
                   for m in d.pop("moments", []) or []]
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(moments=moments, **known)


def year_of(when: str) -> int | None:
    m = _YEAR.search(when or "")
    return int(m.group(1)) if m else None


def _clean_str(value: Any, limit: int = 400) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _uniq(items: list[str], limit: int) -> list[str]:
    seen, out = set(), []
    for it in items:
        key = it.casefold()
        if it and key not in seen:
            seen.add(key)
            out.append(it)
    return out[:limit]


def _as_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def parse_card(raw: Any) -> dict:
    """Coerce Gemma's reply into the card shape, dropping anything malformed."""
    raw = raw if isinstance(raw, dict) else {}
    people = []
    for p in _as_list(raw.get("people")):
        if isinstance(p, dict) and _clean_str(p.get("name"), 80):
            people.append({"name": _clean_str(p.get("name"), 80), "relation": _clean_str(p.get("relation"), 80)})
        elif isinstance(p, str) and p.strip():
            people.append({"name": _clean_str(p, 80), "relation": ""})
    years = []
    for y in _as_list(raw.get("years")):
        if isinstance(y, dict) and _clean_str(y.get("when"), 60):
            years.append({"when": _clean_str(y.get("when"), 60), "what": _clean_str(y.get("what"), 200)})
    moments = []
    for m in _as_list(raw.get("moments")):
        if isinstance(m, dict) and _clean_str(m.get("quote"), 600):
            moments.append({"heading": _clean_str(m.get("heading"), 80), "quote": _clean_str(m.get("quote"), 600)})
    return {
        "title": _clean_str(raw.get("title"), 90),
        "summary": _clean_str(raw.get("summary"), 900),
        "people": people,
        "places": _uniq([_clean_str(p, 80) for p in _as_list(raw.get("places")) if isinstance(p, str)], 20),
        "years": years,
        "moments": moments,
        "themes": _uniq([_clean_str(t, 30).lower() for t in _as_list(raw.get("themes")) if isinstance(t, str)], 6),
        "follow_up_questions": _uniq([_clean_str(q, 200) for q in _as_list(raw.get("follow_up_questions"))
                                      if isinstance(q, str)], 6),
    }


def split_for_card(segments: list[Segment], max_words: int) -> list[list[Segment]]:
    """Split a long transcript into parts of roughly max_words, on segment boundaries."""
    parts: list[list[Segment]] = [[]]
    count = 0
    for seg in segments:
        n = len(seg.text.split())
        if parts[-1] and count + n > max_words:
            parts.append([])
            count = 0
        parts[-1].append(seg)
        count += n
    return [p for p in parts if p]


def _merge_people(lists: list[list[dict]]) -> list[dict]:
    merged: dict[str, dict] = {}
    for lst in lists:
        for p in lst:
            key = p["name"].casefold()
            if key not in merged:
                merged[key] = dict(p)
            elif not merged[key]["relation"] and p["relation"]:
                merged[key]["relation"] = p["relation"]
    return list(merged.values())[:25]


def verify_moments(raw_moments: list[dict], segments: list[Segment],
                   original: list[Segment] | None = None) -> tuple[list[Moment], int]:
    """Keep only moments whose quote is really in the transcript, in the transcript's words."""
    words = words_of(segments)
    kept: list[Moment] = []
    dropped = 0
    seen_spans: set[tuple[int, int]] = set()
    for m in raw_moments:
        match = find_quote(m["quote"], segments, words=words)
        if match is None:
            dropped += 1
            continue
        span = (match.seg_first, match.seg_last)
        if span in seen_spans:
            continue
        seen_spans.add(span)
        kept.append(Moment(
            heading=m["heading"] or "A memory",
            quote=match.text,
            start=match.start,
            end=match.end,
            score=match.score,
            original=overlapping_text(original or [], match.start, match.end) if original else "",
        ))
    kept.sort(key=lambda mo: (mo.start is None, mo.start or 0.0))
    return kept, dropped


def make_card(llm: ChatLLM, segments: list[Segment], *, speaker: str, about: str = "",
              max_words: int = 2800, original: list[Segment] | None = None) -> Card:
    """Ask Gemma for a memory card (in parts for long recordings) and verify its quotes."""
    started = time.perf_counter()
    parts = split_for_card(segments, max_words)
    about_txt = f" about {about}" if about else ""
    parsed: list[dict] = []
    for i, part in enumerate(parts, 1):
        part_note = f"\nThis is part {i} of {len(parts)} of a longer recording." if len(parts) > 1 else ""
        n_moments = "3 to 5" if len(parts) == 1 else "2 or 3"
        prompt = CARD_PROMPT.format(speaker=speaker, about=about_txt, part_note=part_note,
                                    n_moments=n_moments, transcript=full_text(part))
        parsed.append(parse_card(llm.chat_json(prompt, CARD_SCHEMA)))

    if len(parsed) == 1:
        title, summary = parsed[0]["title"], parsed[0]["summary"]
    else:
        listing = "\n".join(f"Part {i}: {p['title']}. {p['summary']}" for i, p in enumerate(parsed, 1))
        merged = llm.chat_json(MERGE_PROMPT.format(speaker=speaker, parts=listing), MERGE_SCHEMA) or {}
        title = _clean_str(merged.get("title"), 90) or parsed[0]["title"]
        summary = _clean_str(merged.get("summary"), 900) or " ".join(p["summary"] for p in parsed)

    raw_moments = [m for p in parsed for m in p["moments"]]
    moments, dropped = verify_moments(raw_moments, segments, original)
    years = [y for p in parsed for y in p["years"]]
    seen_years: set[str] = set()
    uniq_years = []
    for y in years:
        key = (y["when"] + "|" + y["what"]).casefold()
        if key not in seen_years:
            seen_years.add(key)
            uniq_years.append(y)
    return Card(
        title=title,
        summary=summary,
        people=_merge_people([p["people"] for p in parsed]),
        places=_uniq([pl for p in parsed for pl in p["places"]], 25),
        years=uniq_years[:25],
        moments=moments[:8],
        themes=_uniq([t for p in parsed for t in p["themes"]], 6),
        follow_up_questions=_uniq([q for p in parsed for q in p["follow_up_questions"]], 5),
        dropped_quotes=dropped,
        model_seconds=round(time.perf_counter() - started, 2),
    )
