from seance.archive import Story
from seance.ask import answer_question, render_answer
from seance.search import SearchIndex
from seance.transcript import parse_text_transcript

from conftest import FakeLLM


def _hits(samples, tmp_path, q="mango tree"):
    segs = parse_text_transcript((samples / "grandma_the_house_in_kerala.txt").read_text(encoding="utf-8"))
    s = Story(id="g", title="The house in Kottayam", speaker="Grandma", recorded="2026-10-01T12:00:00",
              added="", segments=segs, audio="recordings/g.wav")
    idx = SearchIndex(tmp_path / "i.json")
    idx.add_story(s, 60)
    return idx.search(q, {"g": s}, k=4)


def test_answer_keeps_verified_citation_and_drops_invented(samples, tmp_path):
    hits = _hits(samples, tmp_path)
    ans = answer_question(FakeLLM(), "Tell me about the mango tree", hits)
    assert ans.found
    assert len(ans.citations) == 1 and ans.dropped == 1
    c = ans.citations[0]
    assert c.start is not None
    assert c.quote in " ".join(seg.text for seg in hits[0].story.working)
    out = render_answer(ans)
    assert "Grandma" in out and c.quote in out


def test_no_hits_means_no_model_call(tmp_path):
    llm = FakeLLM()
    ans = answer_question(llm, "anything", [])
    assert not ans.found and llm.prompts == []


class LyingLLM(FakeLLM):
    def chat_json(self, prompt, schema):
        return {"found": True, "answer": "She said the moon was cheese.",
                "citations": [{"passage": "P1", "quote": "the moon is made of green cheese and so are the stars"}]}


def test_unverifiable_answer_is_flagged_with_passages(samples, tmp_path):
    hits = _hits(samples, tmp_path)
    ans = answer_question(LyingLLM(), "What is the moon made of?", hits)
    assert ans.citations == [] and ans.dropped == 1
    out = render_answer(ans)
    assert "couldn't be matched" in out
    assert "·" in out  # closest passages listed
