import json
from datetime import datetime
from pathlib import Path

import pytest

from seance.pipeline import Seance, recorded_at
from seance.transcribe import Transcription
from seance.transcript import Segment

from conftest import FAKE_QUOTE, FakeLLM


def test_recorded_at_from_file_names(tmp_path):
    for name, expected in [
        ("recording_20261028_141502.wav", datetime(2026, 10, 28, 14, 15, 2)),
        ("Voice 2026-10-28 14.15.02.m4a", datetime(2026, 10, 28, 14, 15, 2)),
        ("PTT-20261028-WA0003.opus", datetime(2026, 10, 28, 12, 0, 0)),
        ("call_recording_+971501234567_20261020.amr", datetime(2026, 10, 20, 12, 0, 0)),
        ("grandma 2026-10-28.mp3", datetime(2026, 10, 28, 12, 0, 0)),
    ]:
        p = tmp_path / name
        p.write_bytes(b"x")
        got = recorded_at(p)
        if expected:
            assert got == expected, name


def test_add_text_story_end_to_end(cfg, samples):
    app = Seance(cfg, llm=FakeLLM())
    res = app.add_file(samples / "grandma_the_house_in_kerala.txt", speaker="Grandma",
                       recorded=datetime(2026, 10, 28, 10, 0))
    s = res.story
    assert s.id == "2026-10-28-the-house-with-the-mango-tree"
    assert s.audio is None and s.duration == 112
    assert res.embedded is True
    assert (cfg.stories_dir / f"{s.id}.json").exists()
    md = (cfg.stories_dir / f"{s.id}.md").read_text(encoding="utf-8")
    assert "## In their words" in md and "[00:31]" in md
    assert FAKE_QUOTE not in md
    archive_md = (cfg.home / "ARCHIVE.md").read_text(encoding="utf-8")
    assert "### Grandma" in archive_md and "## Timeline" in archive_md
    html = (cfg.home / "ofrenda.html").read_text(encoding="utf-8")
    assert "Grandma" in html and "In their words" in html
    log = app.archive.read_log()
    assert log[-1]["event"] == "add" and log[-1]["dropped_quotes"] == 1


def test_speaker_names_are_matched_case_insensitively(cfg, samples):
    app = Seance(cfg, llm=FakeLLM())
    app.add_file(samples / "grandma_the_house_in_kerala.txt", speaker="Grandma")
    res = app.add_file(samples / "grandpa_coming_to_dubai.txt", speaker="grandma")
    assert res.story.speaker == "Grandma"
    assert app.archive.speakers() == [("Grandma", 2)]


def test_ask_and_remove(cfg, samples):
    app = Seance(cfg, llm=FakeLLM())
    a = app.add_file(samples / "grandma_the_house_in_kerala.txt", speaker="Grandma").story
    app.add_file(samples / "grandpa_coming_to_dubai.txt", speaker="Grandpa")
    ans = app.ask("How did Grandpa get to Dubai, by ship from Bombay?")
    assert ans.hits and ans.hits[0].story.speaker == "Grandpa"
    assert ans.citations and ans.citations[0].story.speaker == "Grandpa"
    only = app.ask("mango tree", speaker="Grandma")
    assert all(h.story.speaker == "Grandma" for h in only.hits)
    trash = app.remove(a)
    assert (trash / f"{a.id}.json").exists()
    assert len(app.archive.stories()) == 1
    assert all(c.story_id != a.id for c in app.index.chunks)


def test_works_without_embedding_model(cfg, samples):
    app = Seance(cfg, llm=FakeLLM(embed_ok=False))
    res = app.add_file(samples / "grandpa_coming_to_dubai.txt", speaker="Grandpa")
    assert res.embedded is False
    assert app.ask("abra across the Creek").citations


class FakeTranscriber:
    def __init__(self, translate_segments=None):
        self.translate_segments = translate_segments
        self.calls = []

    def transcribe(self, path, *, translate=False, language=None):
        self.calls.append((Path(path).name, translate))
        self.language = language
        segs = [Segment("Njangal veedinte pinnil oru maavu undayirunnu ennu paranju ammachi chirichu.", 0.0, 6.0),
                Segment("Ella varshavum Mayil theruvu muzhuvan maanga edukkan vannu ennu.", 6.0, 12.0)]
        tr = self.translate_segments if translate else []
        return Transcription(segments=segs, language="ml", duration=12.0, seconds=1.5, translation=tr or [],
                             translate_seconds=1.2 if tr else 0.0)


def test_audio_story_with_translation_stores_both_and_copies_audio(cfg, tmp_path):
    english = [Segment("Behind our house there was a mango tree, she said, and laughed out loud.", 0.0, 6.0),
               Segment("Every year in May the whole street came to pick the mangoes.", 6.0, 12.0)]
    tr = FakeTranscriber(english)
    app = Seance(cfg, llm=FakeLLM(), transcriber=tr)
    audio = tmp_path / "ammachi 2026-10-27.m4a"
    audio.write_bytes(b"fake audio")
    res = app.add_file(audio, speaker="Ammachi", translate=True)
    s = res.story
    assert tr.calls == [("ammachi 2026-10-27.m4a", True)]
    assert s.translation and s.language == "ml"
    assert s.audio == f"recordings/{s.id}.m4a" and (cfg.home / s.audio).exists()
    assert s.card.moments and s.card.moments[0].original.startswith("Njangal")
    md = (cfg.stories_dir / f"{s.id}.md").read_text(encoding="utf-8")
    assert "Transcript (English translation)" in md and "Original transcript (ml)" in md
    html = (cfg.home / "ofrenda.html").read_text(encoding="utf-8")
    assert 'class="play"' in html and s.audio in html


def test_rejects_unknown_files_and_empty_transcripts(cfg, tmp_path):
    app = Seance(cfg, llm=FakeLLM())
    bad = tmp_path / "x.pdf"
    bad.write_text("x")
    with pytest.raises(ValueError):
        app.add_file(bad, speaker="A")
    empty = tmp_path / "empty.txt"
    empty.write_text("# only a comment\n")
    with pytest.raises(ValueError, match="No speech"):
        app.add_file(empty, speaker="A")


def test_unplayable_formats_get_a_listening_copy(cfg, tmp_path, monkeypatch):
    converted = []

    def fake_convert(src, dest):
        converted.append((src.name, dest.name))
        dest.write_bytes(b"RIFF")
        return 12.0

    import seance.audio
    monkeypatch.setattr(seance.audio, "to_listening_wav", fake_convert)
    tr = FakeTranscriber()
    app = Seance(cfg, llm=FakeLLM(), transcriber=tr)
    amr = tmp_path / "Call with Ammachi 2026-10-20.amr"
    amr.write_bytes(b"#!AMR")
    s = app.add_file(amr, speaker="Ammachi", language="ml").story
    assert tr.language == "ml"
    assert converted == [(amr.name, f"{s.id}.wav")]
    assert s.audio == f"recordings/{s.id}.wav" and s.source_name == amr.name
    assert amr.read_bytes() == b"#!AMR"   # original untouched

    opus = tmp_path / "PTT-20261021-WA0001.opus"
    opus.write_bytes(b"OggS")
    s2 = app.add_file(opus, speaker="Ammachi").story
    assert s2.audio.endswith(".opus") and len(converted) == 1   # browsers play opus: copied as is
    assert s2.recorded.startswith("2026-10-21")


def test_failed_listening_copy_keeps_the_story(cfg, tmp_path, monkeypatch):
    import seance.audio

    def broken(src, dest):
        raise RuntimeError("codec missing")

    monkeypatch.setattr(seance.audio, "to_listening_wav", broken)
    app = Seance(cfg, llm=FakeLLM(), transcriber=FakeTranscriber())
    wma = tmp_path / "old.wma"
    wma.write_bytes(b"x")
    s = app.add_file(wma, speaker="Appachan").story
    assert s.audio is None and (cfg.stories_dir / f"{s.id}.json").exists()
