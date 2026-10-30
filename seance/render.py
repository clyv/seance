"""Plain Markdown views of the archive: one file per story, plus ARCHIVE.md as the index."""

from __future__ import annotations

from datetime import datetime

from .archive import Archive, Story, atomic_write_text
from .card import year_of
from .transcript import Segment, fmt_ts


def fmt_duration(seconds: float) -> str:
    seconds = int(round(seconds or 0))
    if seconds < 60:
        return f"{seconds}s"
    m, s = divmod(seconds, 60)
    if m < 60:
        return f"{m} min {s:02d}s" if s else f"{m} min"
    h, m = divmod(m, 60)
    return f"{h} h {m:02d} min"


def transcript_lines(segments: list[Segment]) -> list[str]:
    out = []
    for s in segments:
        ts = fmt_ts(s.start)
        out.append(f"[{ts}] {s.text}" if ts else s.text)
        if not ts:
            out.append("")
    return out


def story_markdown(story: Story) -> str:
    c = story.card
    meta = [f"**{story.speaker}**", f"recorded {story.recorded_date}"]
    if story.duration:
        meta.append(fmt_duration(story.duration))
    if story.language:
        meta.append(f"language: {story.language}")
    lines = [f"# {story.title}", "", " · ".join(meta), ""]
    if c.summary:
        lines += [f"> {c.summary}", ""]
    if c.moments:
        lines += ["## In their words", ""]
        for m in c.moments:
            ts = fmt_ts(m.start)
            lines.append(f"- **{m.heading}**" + (f" ({ts})" if ts else ""))
            lines.append(f"  > “{m.quote}”")
            if m.original:
                lines.append(f"  > _Original: {m.original}_")
        lines.append("")
    if c.people:
        lines += ["## People", ""] + [
            f"- {p['name']}" + (f" ({p['relation']})" if p.get("relation") else "") for p in c.people
        ] + [""]
    if c.places:
        lines += ["## Places", ""] + [f"- {p}" for p in c.places] + [""]
    if c.years:
        years = sorted(c.years, key=lambda y: (year_of(y["when"]) is None, year_of(y["when"]) or 0))
        lines += ["## When", ""] + [f"- **{y['when']}**: {y['what']}" for y in years] + [""]
    if c.themes:
        lines += ["## Themes", "", ", ".join(c.themes), ""]
    if c.follow_up_questions:
        lines += [f"## Questions to ask {story.speaker} next time", ""]
        lines += [f"- {q}" for q in c.follow_up_questions] + [""]
    if story.translation:
        lines += ["## Transcript (English translation)", ""] + transcript_lines(story.translation) + [""]
        lines += [f"## Original transcript ({story.language})", ""] + transcript_lines(story.segments) + [""]
    else:
        lines += ["## Transcript", ""] + transcript_lines(story.segments) + [""]
    if c.dropped_quotes:
        lines += [f"<!-- {c.dropped_quotes} suggested quote(s) were left out because they weren't in the transcript -->", ""]
    return "\n".join(lines).rstrip() + "\n"


def archive_markdown(archive: Archive, now: datetime | None = None) -> str:
    stories = archive.stories()
    people = archive.people()
    now = now or datetime.now()
    total = sum(s.duration for s in stories)
    lines = ["# 🕯️ Family archive", ""]
    lines.append(f"_{len(stories)} {'story' if len(stories) == 1 else 'stories'}"
                 + (f" · {fmt_duration(total)} of recordings" if total else "")
                 + f" · updated {now:%a %d %b %Y}_")
    lines.append("")
    if not stories:
        lines += ["No stories yet. Add one with `seance record` or `seance add FILE --speaker NAME`.", ""]
        return "\n".join(lines)

    lines += ["## People", ""]
    for name, count in archive.speakers():
        info = people.get(name, {})
        extra = ", ".join(x for x in (info.get("relation"), info.get("years")) if x)
        lines.append(f"### {name}" + (f" ({extra})" if extra else ""))
        lines.append("")
        for s in [s for s in stories if s.speaker == name]:
            first = s.card.summary.split(". ")[0].rstrip(".") + "." if s.card.summary else ""
            lines.append(f"- [{s.title}](stories/{s.id}.md) · {s.recorded_date} · {first}".rstrip(" ·"))
        if count == 0:
            lines.append("- _No recordings yet._")
        lines.append("")

    timeline = []
    for s in stories:
        for y in s.card.years:
            yr = year_of(y["when"])
            if yr is not None:
                timeline.append((yr, y, s))
    if timeline:
        lines += ["## Timeline", ""]
        for yr, y, s in sorted(timeline, key=lambda t: (t[0], t[2].recorded)):
            lines.append(f"- **{y['when']}**: {y['what']} ({s.speaker}, [{s.title}](stories/{s.id}.md))")
        lines.append("")

    places: dict[str, list[Story]] = {}
    for s in stories:
        for p in s.card.places:
            places.setdefault(p, [])
            if s not in places[p]:
                places[p].append(s)
    if places:
        lines += ["## Places", ""]
        for p in sorted(places, key=str.casefold):
            lines.append(f"- **{p}**: " + ", ".join(f"[{s.title}](stories/{s.id}.md)" for s in places[p]))
        lines.append("")

    asks = [(s.speaker, q) for s in stories for q in s.card.follow_up_questions]
    if asks:
        lines += ["## Questions for next time", ""]
        for name in dict.fromkeys(n for n, _ in asks):
            lines.append(f"**{name}**")
            lines.append("")
            lines += [f"- {q}" for n, q in asks if n == name]
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_story(archive: Archive, story: Story) -> None:
    atomic_write_text(archive.cfg.stories_dir / f"{story.id}.md", story_markdown(story))


def write_index(archive: Archive) -> None:
    atomic_write_text(archive.home / "ARCHIVE.md", archive_markdown(archive))
