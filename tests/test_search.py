from seance.archive import Story
from seance.search import BM25, SearchIndex, chunk_segments, cosine, tokenize
from seance.transcript import Segment

from conftest import FakeLLM


def _story(sid, speaker, texts, title="A story"):
    segs = [Segment(t, i * 10.0, i * 10.0 + 10) for i, t in enumerate(texts)]
    return Story(id=sid, title=title, speaker=speaker, recorded="2026-10-01T12:00:00", added="", segments=segs)


def test_chunks_cover_everything_and_overlap():
    segs = [Segment(" ".join(["word"] * 30), i * 10.0, i * 10.0 + 10) for i in range(10)]
    chunks = chunk_segments("s", segs, chunk_words=70)
    assert chunks[0].seg_first == 0 and chunks[-1].seg_last == 9
    for a, b in zip(chunks, chunks[1:]):
        assert b.seg_first == a.seg_last          # one segment of overlap
    assert all(c.start is not None for c in chunks)


def test_huge_single_segment_still_chunks():
    segs = [Segment(" ".join(["word"] * 500), 0, 100)]
    assert len(chunk_segments("s", segs, 50)) == 1


def test_tokenize_drops_stopwords_and_plurals():
    assert tokenize("The mangoes and the trees") == ["mangoe", "tree"]


def test_bm25_prefers_matching_doc():
    bm = BM25([tokenize("ship from bombay"), tokenize("mango tree by the well")])
    s = bm.scores(tokenize("mango"))
    assert s[1] > s[0] == 0


def test_cosine():
    assert cosine([1, 0], [1, 0]) == 1.0
    assert cosine([1, 0], [0, 1]) == 0.0
    assert cosine([], []) == 0.0


def test_index_search_keywords_and_speaker_filter(tmp_path):
    a = _story("a", "Grandma", ["The mango tree stood by the well.", "Father read the newspaper."])
    b = _story("b", "Grandpa", ["I came on a ship from Bombay.", "We crossed the Creek by abra and ate mango."])
    idx = SearchIndex(tmp_path / "index.json")
    idx.add_story(a, 110)
    idx.add_story(b, 110)
    idx.save()
    idx2 = SearchIndex(tmp_path / "index.json")
    stories = {"a": a, "b": b}
    hits = idx2.search("ship from Bombay", stories)
    assert hits[0].story.id == "b"
    only = idx2.search("mango", stories, speaker="grandma")
    assert {h.story.id for h in only} == {"a"}
    assert idx2.search("zeppelin", stories) == []


def test_embeddings_are_stored_and_used(tmp_path):
    llm = FakeLLM()
    a = _story("a", "Grandma", ["The mango tree stood by the well."])
    b = _story("b", "Grandpa", ["I came on a ship from Bombay."])
    idx = SearchIndex(tmp_path / "index.json")
    assert idx.add_story(a, 110, llm) is True
    assert idx.add_story(b, 110, llm) is True
    assert idx.has_vectors and idx.embed_model == "embeddinggemma"
    hits = idx.search("Bombay ship", {"a": a, "b": b}, embedder=llm)
    assert hits[0].story.id == "b"


def test_adding_without_embedder_falls_back_to_keywords_everywhere(tmp_path):
    llm = FakeLLM()
    idx = SearchIndex(tmp_path / "index.json")
    idx.add_story(_story("a", "G", ["one two three"]), 110, llm)
    assert idx.has_vectors
    idx.add_story(_story("b", "G", ["four five six"]), 110, None)
    assert not idx.has_vectors and idx.embed_model is None
    assert idx.rebuild([_story("a", "G", ["x y z"])], 110, llm) is True
    assert idx.has_vectors


def test_card_headings_make_passages_findable_by_their_meaning(tmp_path):
    from seance.card import Card, Moment
    s = _story("a", "Grandma", ["We were young then.", "The water came right up to the verandah steps.",
                                "Father read the paper."])
    s.card = Card(moments=[Moment("The 1961 flood", "The water came right up to the verandah steps.", 10.0, 20.0)])
    idx = SearchIndex(tmp_path / "i.json")
    idx.add_story(s, 8)
    hits = idx.search("what was the flood like", {"a": s})
    assert hits and "verandah" in hits[0].chunk.text
