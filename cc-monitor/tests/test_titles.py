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
