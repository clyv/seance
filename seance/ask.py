"""Ask the archive a question; get an answer backed by the speakers' own words.

Gemma reads the best-matching passages and answers, citing passages and
quoting them. Each quote is then checked against the transcript; only quotes
that are really there, with their timestamps, are shown.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from .archive import Story
from .card import ChatLLM
from .search import Hit
from .transcript import find_quote, fmt_ts

ANSWER_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "found": {"type": "boolean"},
        "answer": {"type": "string"},
        "citations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"passage": {"type": "string"}, "quote": {"type": "string"}},
                "required": ["passage", "quote"],
            },
        },
    },
    "required": ["found", "answer", "citations"],
}

ASK_PROMPT = """You keep a family's archive of recorded stories. Answer the question using ONLY
the passages below. They are transcribed from recordings of family members talking.

Question: {question}

Passages:
{passages}

Rules:
- Answer in 2 to 4 plain, warm sentences, in the third person ("{example} said ...").
- Every fact must come from the passages. Never invent what someone said, felt or meant.
- If the passages don't answer the question, set found to false and say in one sentence
  what the recordings do talk about instead.
- Give 1 to 3 citations. Each names a passage id (like P2) and copies a short quote from that
  passage EXACTLY, word for word, 8 to 30 words.
"""


@dataclass
class Citation:
    story: Story
    quote: str
    start: float | None
    end: float | None

    @property
    def where(self) -> str:
        ts = fmt_ts(self.start)
        return f"{self.story.speaker}, “{self.story.title}”" + (f" at {ts}" if ts else "")


@dataclass
class Answer:
    question: str
    text: str
    found: bool
    citations: list[Citation] = field(default_factory=list)
    hits: list[Hit] = field(default_factory=list)
    dropped: int = 0          # citations Gemma gave that weren't in the transcript
    seconds: float = 0.0

    @property
    def verified(self) -> bool:
        return bool(self.citations)


def format_passages(hits: list[Hit]) -> str:
    lines = []
    for i, h in enumerate(hits, 1):
        ts = fmt_ts(h.chunk.start)
        when = f" at {ts}" if ts else ""
        lines.append(f'[P{i}] {h.story.speaker}, "{h.story.title}"{when}:\n{h.chunk.text}')
    return "\n\n".join(lines)


def _verify(passage_id: str, quote: str, hits: list[Hit]) -> Citation | None:
    try:
        idx = int(passage_id.strip().upper().lstrip("P[").rstrip("]")) - 1
    except ValueError:
        idx = -1
    order = [hits[idx]] if 0 <= idx < len(hits) else []
    order += [h for h in hits if h not in order]
    for h in order:
        segs = h.story.working[h.chunk.seg_first:h.chunk.seg_last + 1]
        m = find_quote(quote, segs, min_score=0.7)
        if m is not None:
            return Citation(h.story, m.text, m.start, m.end)
    return None


def answer_question(llm: ChatLLM, question: str, hits: list[Hit]) -> Answer:
    started = time.perf_counter()
    if not hits:
        return Answer(question, "The recordings don't seem to mention that yet.", False, seconds=0.0)
    example = hits[0].story.speaker or "Grandma"
    prompt = ASK_PROMPT.format(question=question.strip(), passages=format_passages(hits), example=example)
    raw = llm.chat_json(prompt, ANSWER_SCHEMA) or {}
    text = " ".join(str(raw.get("answer") or "").split())
    found = bool(raw.get("found", True))
    citations: list[Citation] = []
    dropped = 0
    seen: set[str] = set()
    for c in raw.get("citations") if isinstance(raw.get("citations"), list) else []:
        if not isinstance(c, dict):
            continue
        cit = _verify(str(c.get("passage", "")), str(c.get("quote", "")), hits)
        if cit is None:
            dropped += 1
        elif cit.quote not in seen:
            seen.add(cit.quote)
            citations.append(cit)
    return Answer(question, text, found, citations[:3], hits, dropped, round(time.perf_counter() - started, 2))


def render_answer(ans: Answer, *, show_passages: bool = False) -> str:
    lines = [f"🕯️  {ans.text}" if ans.text else "🕯️  (no answer)"]
    if ans.found and not ans.citations:
        lines.append("")
        lines.append("   ⚠ Gemma's answer couldn't be matched to anything actually said, so treat it")
        lines.append("     with care. These are the closest passages in the recordings:")
        show_passages = True
    for c in ans.citations:
        lines.append("")
        lines.append(f"   “{c.quote}”")
        lines.append(f"      — {c.where}")
    if show_passages and ans.hits:
        lines.append("")
        for h in ans.hits[:3]:
            ts = fmt_ts(h.chunk.start)
            snippet = h.chunk.text if len(h.chunk.text) < 220 else h.chunk.text[:217] + "..."
            lines.append(f"   · {h.story.speaker}, “{h.story.title}”{' at ' + ts if ts else ''}: {snippet}")
    return "\n".join(lines)
