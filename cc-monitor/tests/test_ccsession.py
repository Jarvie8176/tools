"""cc-session health is an OPTIONAL enrichment: read() signals presence via None vs dict."""
from cc_monitor import ccsession


def test_read_returns_none_when_absent(tmp_path):
    # no claude.prom -> cc-session not on this host; caller renders a standalone view
    assert ccsession.read(str(tmp_path)) is None


def test_read_parses_flat_dict_when_present(tmp_path):
    (tmp_path / "claude.prom").write_text("rc_connected=1\nauth_healthy=1\nworkers=3\n")
    assert ccsession.read(str(tmp_path)) == {"rc_connected": "1", "auth_healthy": "1", "workers": "3"}


def test_read_present_but_empty_is_dict_not_none(tmp_path):
    # present-but-empty ({}) is distinct from absent (None) — the file exists, just has no health yet
    (tmp_path / "claude.prom").write_text("")
    assert ccsession.read(str(tmp_path)) == {}
