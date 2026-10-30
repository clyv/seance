from seance.card import Card, make_card, parse_card, split_for_card, verify_moments, year_of
from seance.transcript import Segment, parse_text_transcript

from conftest import FAKE_QUOTE, FakeLLM


def test_parse_card_coerces_bad_shapes():
    raw = {
        "title": "  A   title ",
        "people": ["Joseph", {"name": "Annamma", "relation": "sister"}, {"relation": "no name"}],
        "places": ["Kottayam", "kottayam", 5],
        "years": [{"when": "1961", "what": "flood"}, {"what": "no when"}],
        "moments": [{"heading": "x", "quote": "q"}, {"heading": "empty"}],
        "themes": ["Family", "family"],
        "follow_up_questions": "not a list",
    }
    c = parse_card(raw)
    assert c["title"] == "A title"
    assert [p["name"] for p in c["people"]] == ["Joseph", "Annamma"]
    assert c["places"] == ["Kottayam"]
    assert len(c["years"]) == 1 and len(c["moments"]) == 1
    assert c["themes"] == ["family"]
    assert c["follow_up_questions"] == []
    assert parse_card(None)["moments"] == []


def test_year_of():
    assert year_of("1961") == 1961
    assert year_of("the 1970s") == 1970
    assert year_of("when I was ten") is None


def test_verify_moments_keeps_real_drops_invented(samples):
    segs = parse_text_transcript((samples / "grandma_the_house_in_kerala.txt").read_text(encoding="utf-8"))
    moments, dropped = verify_moments([
        {"heading": "Mangoes", "quote": "Every May the whole street came for our mangoes"},
        {"heading": "Fake", "quote": FAKE_QUOTE},
        {"heading": "Same again", "quote": "every May the whole street came for our mangoes"},
    ], segs)
    assert dropped == 1
    assert len(moments) == 1  # duplicate span collapsed
    assert moments[0].start == 31
    assert moments[0].quote.startswith("Every May the whole street came")


def test_make_card_single_part(samples):
    llm = FakeLLM()
    segs = parse_text_transcript((samples / "grandma_the_house_in_kerala.txt").read_text(encoding="utf-8"))
    card = make_card(llm, segs, speaker="Grandma")
    assert card.title == "The house with the mango tree"
    assert card.dropped_quotes == 1           # the invented banana-leaf quote
    assert len(card.moments) == 2
    assert all(m.start is not None for m in card.moments)
    assert {y["when"] for y in card.years} >= {"1958", "1961", "1965"}
    assert len(llm.prompts) == 1
    assert "Grandma" in llm.prompts[0]


def test_make_card_long_recording_in_parts():
    segs = [Segment(f"Sentence number {i} is about the old house and the long verandah.", i * 5.0, i * 5.0 + 5)
            for i in range(60)]
    llm = FakeLLM()
    card = make_card(llm, segs, speaker="Grandpa", max_words=150)
    parts = split_for_card(segs, 150)
    assert len(parts) > 1
    assert len(llm.prompts) == len(parts) + 1   # one per part, plus the merge
    assert card.title == "Merged title"
    assert "part 1 of" in llm.prompts[0]


def test_card_round_trip():
    c = Card(title="t", moments=[], years=[{"when": "1961", "what": "x"}])
    assert Card.from_dict(c.to_dict()) == c
