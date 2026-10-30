from agent.verify import bad_numbers, facts_from, split_sentences, with_percentages


def test_numbers_must_come_from_facts():
    facts = with_percentages(facts_from({"n": 128, "rejects": 4, "ref_ah": 2.4949, "ir": [25.71, 50.52]}), [128])
    ids = ["A07", "G12", "B16"]
    assert bad_numbers("All 128 channels were graded; 4 were rejected.", facts, ids) == []
    assert bad_numbers("Reference capacity was 2.49 Ah.", facts, ids) == []          # rounding of 2.4949
    assert bad_numbers("Channel G12 measured 50.5 mOhm.", facts, ids) == []          # G12 is an ID, not a number
    assert bad_numbers("About 3.1% of channels were rejected.", facts, ids) == []    # 4/128 = 3.125%
    assert bad_numbers("Reference capacity was 2.61 Ah.", facts, ids) == ["2.61"]
    assert bad_numbers("Channel A07 lost 7% of capacity.", facts, ids) == ["7%"]


def test_sentence_split_keeps_decimals():
    s = split_sentences("Capacity was 2.49 Ah. G12 needs review! Done.")
    assert s == ["Capacity was 2.49 Ah.", "G12 needs review!", "Done."]
