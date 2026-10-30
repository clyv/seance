from datetime import datetime

from seance.archive import Archive, Story, slugify
from seance.card import Card, Moment
from seance.ofrenda import build_ofrenda
from seance.render import archive_markdown, fmt_duration, story_markdown
from seance.transcript import Segment


def _story(**kw):
    card = Card(title="T", summary="Summary here.", places=["Kottayam"], themes=["home"],
                years=[{"when": "1961", "what": "the flood"}, {"when": "as a child", "what": "games"}],
                moments=[Moment("Mangoes", "the whole street came for our mangoes", 31.0, 44.0)],
                follow_up_questions=["Who bought the house?"])
    base = dict(id="2026-10-28-t", title="The <house>", speaker="Grandma <script>", recorded="2026-10-28T10:00:00",
                added="", segments=[Segment("Hello.", 0.0, 2.0)], card=card, audio="recordings/2026-10-28-t.m4a",
                duration=125.0)
    base.update(kw)
    return Story(**base)


def test_fmt_duration():
    assert fmt_duration(42) == "42s"
    assert fmt_duration(125) == "2 min 05s"
    assert fmt_duration(3700) == "1 h 01 min"


def test_slugify():
    assert slugify("Séance: the house in Kottayam!") == "seance-the-house-in-kottayam"
    assert slugify("!!!") == "story"


def test_story_markdown_sections():
    md = story_markdown(_story())
    assert md.startswith("# The <house>")
    assert "- **Mangoes** (00:31)" in md
    assert "## When" in md and md.index("1961") < md.index("as a child")
    assert "## Questions to ask Grandma <script> next time" in md
    assert "[00:00] Hello." in md


def test_ofrenda_escapes_and_plays(cfg):
    arch = Archive(cfg)
    arch.save(_story())
    arch.set_person("Grandma <script>", relation="Dad's mother", years="1938–2019")
    html = build_ofrenda(arch, now=datetime(2026, 10, 31))
    assert "<script>alert" not in html
    assert "Grandma &lt;script&gt;" in html
    assert 'data-src="recordings/2026-10-28-t.m4a" data-start="31.0"' in html
    assert "Dad&#x27;s mother" in html
    assert "Through the years" in html and "the flood" in html
    assert 'id="filter"' in html


def test_ofrenda_text_story_has_no_play_button(cfg):
    arch = Archive(cfg)
    arch.save(_story(audio=None))
    assert 'class="play"' not in build_ofrenda(arch)


def test_empty_archive_views(cfg):
    arch = Archive(cfg)
    assert "No stories yet" in archive_markdown(arch)
    assert "No stories yet" in build_ofrenda(arch)


def test_archive_find(cfg):
    arch = Archive(cfg)
    arch.save(_story())
    arch.save(_story(id="2026-10-29-other", title="Another tale"))
    assert arch.find("2026-10-28-t").title == "The <house>"
    assert arch.find("another").id == "2026-10-29-other"
    assert arch.find("zzz") is None
    import pytest
    with pytest.raises(LookupError):
        arch.find("2026-10-2")
