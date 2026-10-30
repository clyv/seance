from seance.transcript import (Segment, find_quote, fmt_ts, overlapping_text, parse_text_transcript,
                               parse_ts, word_count)


def test_fmt_and_parse_ts():
    assert fmt_ts(0) == "00:00"
    assert fmt_ts(72.4) == "01:12"
    assert fmt_ts(3725) == "1:02:05"
    assert fmt_ts(None) == ""
    assert parse_ts("03:12") == 192
    assert parse_ts("1:02:05") == 3725
    assert parse_ts("nope") is None


def test_parse_timestamped_transcript_with_continuation_lines():
    segs = parse_text_transcript("# heading\n[00:00] Hello there.\n[00:05] We had a mango tree,\nby the well.\n[01:10] End.")
    assert [s.start for s in segs] == [0, 5, 70]
    assert segs[1].text == "We had a mango tree, by the well."
    assert segs[0].end == 5 and segs[1].end == 70 and segs[2].end is None


def test_parse_plain_timestamps_and_ranges():
    segs = parse_text_transcript("0:03 first line here\n[00:10] - [00:14] second line")
    assert segs[0].start == 3 and segs[0].text == "first line here"
    assert segs[1].start == 10 and segs[1].end == 14


def test_parse_paragraphs_without_timestamps():
    segs = parse_text_transcript("First paragraph\ncontinues here.\n\nSecond one.\n")
    assert [s.text for s in segs] == ["First paragraph continues here.", "Second one."]
    assert all(s.start is None for s in segs)
    assert word_count(segs) == 6


def _segs():
    return parse_text_transcript(
        "[00:00] Okay, is it recording?\n"
        "[00:04] Behind the house there was a well, and next to the well there was a mango tree.\n"
        "[00:12] Every May the whole street came for our mangoes.\n"
        "[00:20] My father was strict.\n")


def test_find_exact_quote_returns_transcript_words_and_time():
    m = find_quote("next to the well there was a mango tree", _segs())
    assert m is not None
    assert m.text == "next to the well there was a mango tree."
    assert m.start == 4 and m.score == 1.0


def test_find_quote_spanning_segments_and_slightly_misquoted():
    m = find_quote("there was a mango tree, every May the whole street came for the mangoes", _segs())
    assert m is not None
    assert m.start == 4 and m.end == 20
    assert "Every May the whole street came" in m.text
    assert m.score >= 0.8


def test_invented_quote_is_rejected():
    assert find_quote("my father was the kindest man in the whole village", _segs()) is None


def test_short_quote_needs_exact_match():
    assert find_quote("father was strict", _segs()) is not None
    assert find_quote("mother was strict", _segs()) is None


def test_ellipsis_stitched_quote_uses_longest_piece():
    m = find_quote("Behind the house there was a well ... the whole street came for our mangoes", _segs())
    assert m is not None


def test_overlapping_text_for_original_language():
    original = [Segment("ഒന്ന്", 0, 4), Segment("രണ്ട്", 4, 12), Segment("മൂന്ന്", 12, 20)]
    assert overlapping_text(original, 5, 11) == "രണ്ട്"
    assert overlapping_text(original, 3, 13) == "ഒന്ന് രണ്ട് മൂന്ന്"
    assert overlapping_text(original, None, None) == ""


def test_malayalam_vowel_signs_are_kept_when_matching():
    from seance.transcript import norm
    assert norm("മാവ്") != norm("മവ")
    segs = [Segment("ഞങ്ങൾ ചെറുപ്പമായിരുന്നു.", 0, 4),
            Segment("അമ്മച്ചിയുടെ വീട്ടിൽ ഒരു വലിയ മാവ് ഉണ്ടായിരുന്നു, എല്ലാ മെയ് മാസത്തിലും.", 4, 10)]
    m = find_quote("അമ്മച്ചിയുടെ വീട്ടിൽ ഒരു വലിയ മാവ് ഉണ്ടായിരുന്നു", segs)
    assert m is not None and m.start == 4 and m.score == 1.0
    assert find_quote("അമ്മച്ചിയുടെ വീട്ടിൽ ഒരു വലിയ പശു ഉണ്ടായിരുന്നു എന്ന് പറഞ്ഞു കേട്ടിട്ടില്ല", segs) is None
