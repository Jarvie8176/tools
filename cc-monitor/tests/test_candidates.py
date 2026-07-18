from cc_monitor import candidates


def test_missing_file_is_empty(claude):
    assert candidates.load() == {}


def test_corrupt_file_degrades_gracefully(claude):
    with open(claude.candidates_file, "w") as fh:
        fh.write("{not valid json")
    assert candidates.load() == {}


def test_get_present_and_absent(claude):
    claude.candidates({"claude-opus-4-8": 1_000_000})
    c = candidates.load()
    assert candidates.get(c, "claude-opus-4-8") == 1_000_000
    assert candidates.get(c, "claude-sonnet-5") is None


def test_get_rejects_non_positive_and_garbage(claude):
    claude.candidates({"a": 0, "b": -1, "c": "x"})
    c = candidates.load()
    assert candidates.get(c, "a") is None
    assert candidates.get(c, "b") is None
    assert candidates.get(c, "c") is None


def test_save_records_value(claude):
    candidates.save("claude-opus-4-8", 1_000_000)
    assert candidates.load() == {"claude-opus-4-8": 1_000_000}


def test_save_ignores_non_positive(claude):
    candidates.save("m", 0)
    candidates.save("m", -5)
    assert candidates.load() == {}


def test_save_preserves_other_models(claude):
    claude.candidates({"keep": 200_000})
    candidates.save("new", 1_000_000)
    assert candidates.load() == {"keep": 200_000, "new": 1_000_000}


def test_save_over_corrupt_file_degrades_not_crashes(claude):
    with open(claude.candidates_file, "w") as fh:
        fh.write("{not json")
    candidates.save("m", 500_000)
    assert candidates.load() == {"m": 500_000}
