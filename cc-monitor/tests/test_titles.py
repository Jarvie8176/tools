from cc_monitor import titles


def test_missing_file_is_empty(claude):
    assert titles.load() == {}


def test_corrupt_file_degrades_gracefully(claude):
    with open(claude.titles_file, "w") as fh:
        fh.write("{not valid json")
    assert titles.load() == {}


def test_resolve_by_session_id(claude):
    claude.titles({"uuid-1": "My Session"})
    assert titles.resolve(titles.load(), "uuid-1", None) == "My Session"


def test_resolve_by_bridge_id(claude):
    claude.titles({"session_abc": "Bridged"})
    assert titles.resolve(titles.load(), "uuid-x", "session_abc") == "Bridged"


def test_session_id_takes_precedence_over_bridge(claude):
    claude.titles({"uuid-1": "ByUuid", "session_abc": "ByBridge"})
    assert titles.resolve(titles.load(), "uuid-1", "session_abc") == "ByUuid"


def test_no_match_returns_empty(claude):
    assert titles.resolve({}, "uuid-1", "session_abc") == ""


def test_non_string_value_coerced_not_crash(claude):
    # a hand-edit typo (missing quotes) must not later crash render via trunc(int)
    assert titles.resolve({"uuid-1": 42}, "uuid-1", None) == "42"


def test_save_sets_then_resolves(claude):
    titles.save("uuid-1", "Renamed")
    assert titles.load() == {"uuid-1": "Renamed"}
    assert titles.resolve(titles.load(), "uuid-1", None) == "Renamed"


def test_save_empty_clears_key(claude):
    titles.save("uuid-1", "X")
    titles.save("uuid-1", "")                       # empty -> clear the override
    assert "uuid-1" not in titles.load()


def test_save_trims_and_preserves_other_keys(claude):
    claude.titles({"uuid-1": "Keep"})
    titles.save("session_abc", "  Trimmed  ")       # whitespace trimmed; other key untouched
    got = titles.load()
    assert got["session_abc"] == "Trimmed" and got["uuid-1"] == "Keep"


def test_save_over_corrupt_file_degrades_not_crashes(claude):
    with open(claude.titles_file, "w") as fh:
        fh.write("{not json")
    titles.save("uuid-1", "Fresh")                  # corrupt base -> {} then set (no crash)
    assert titles.load() == {"uuid-1": "Fresh"}
