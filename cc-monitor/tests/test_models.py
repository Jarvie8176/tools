from cc_monitor import models


def test_missing_file_is_empty(claude):
    assert models.load() == {}


def test_corrupt_file_degrades_gracefully(claude):
    with open(claude.models_file, "w") as fh:
        fh.write("{not valid json")
    assert models.load() == {}


def test_alias_and_override_lookup(claude):
    claude.models({"claude-opus-4-8": {"alias": "Opus", "window": 500_000}})
    m = models.load()
    assert models.alias_of(m, "claude-opus-4-8") == "Opus"
    assert models.override_of(m, "claude-opus-4-8") == 500_000


def test_lookup_absent_model(claude):
    m = models.load()
    assert models.alias_of(m, "claude-opus-4-8") == ""
    assert models.override_of(m, "claude-opus-4-8") is None


def test_override_rejects_non_positive_and_garbage(claude):
    claude.models({"a": {"window": 0}, "b": {"window": -5}, "c": {"window": "nope"}})
    m = models.load()
    assert models.override_of(m, "a") is None
    assert models.override_of(m, "b") is None
    assert models.override_of(m, "c") is None


def test_save_alias_only(claude):
    models.save("claude-opus-4-8", alias="Big")
    assert models.load() == {"claude-opus-4-8": {"alias": "Big"}}


def test_save_window_only(claude):
    models.save("claude-opus-4-8", window=1_000_000)
    assert models.load() == {"claude-opus-4-8": {"window": 1_000_000}}


def test_save_both_then_partial_update_leaves_other_field(claude):
    models.save("m", alias="A", window=300_000)
    models.save("m", window=400_000)                 # alias not supplied -> untouched
    assert models.load()["m"] == {"alias": "A", "window": 400_000}


def test_clear_alias_keeps_window(claude):
    models.save("m", alias="A", window=300_000)
    models.save("m", alias="")                        # empty alias clears just that field
    assert models.load()["m"] == {"window": 300_000}


def test_clearing_last_field_drops_model_entry(claude):
    models.save("m", alias="A")
    models.save("m", alias="")                         # entry now empty -> whole key dropped
    assert "m" not in models.load()


def test_clear_window_via_zero(claude):
    models.save("m", window=500_000)
    models.save("m", window=0)                          # 0 clears the override
    assert "m" not in models.load()


def test_alias_trimmed_and_capped(claude):
    models.save("m", alias="  " + "x" * 200 + "  ")
    got = models.load()["m"]["alias"]
    assert got == "x" * 64 and len(got) == 64          # trimmed + capped to _MAX_ALIAS


def test_save_preserves_other_models(claude):
    claude.models({"keep": {"alias": "K"}})
    models.save("new", window=200_000)
    m = models.load()
    assert m["keep"] == {"alias": "K"} and m["new"] == {"window": 200_000}


def test_save_over_corrupt_file_degrades_not_crashes(claude):
    with open(claude.models_file, "w") as fh:
        fh.write("{not json")
    models.save("m", alias="Fresh")
    assert models.load() == {"m": {"alias": "Fresh"}}
