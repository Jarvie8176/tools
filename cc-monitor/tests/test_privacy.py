"""Server-side redaction: the masking primitive + its application in HTML/text/API output."""
import json

from cc_monitor import config, privacy, render, stream


def test_redact_masks_nonempty_to_fixed_marker_when_on():
    assert privacy.redact("secret prompt", True) == privacy.MARKER


def test_redact_marker_is_length_independent():
    # must not leak even the length of the masked text
    assert privacy.redact("a", True) == privacy.redact("a" * 500, True) == privacy.MARKER


def test_redact_passthrough_when_off():
    assert privacy.redact("secret", False) == "secret"


def test_redact_empty_stays_empty_so_placeholder_wins():
    assert privacy.redact("", True) == ""       # caller's own "—" fallback still renders
    assert privacy.redact(None, True) is None


def _render_row(**kw):
    base = {"status": "idle", "ctx": 0, "win": 200000, "win_certain": True, "cum_input": 0,
            "cum_output": 0, "full": True, "idle_s": 1, "name": "n", "model": "m",
            "bridge_short": "-", "u8": "abcd1234", "last_prompt": "", "override_title": "",
            "custom_title": ""}
    base.update(kw)
    return base


def test_html_redacts_prompt_and_title_when_enabled():
    cfg = {**config.DEFAULTS, "redact_default": True}
    out = render._row_html(_render_row(last_prompt="buy AAPL at open", custom_title="secret plan"), cfg)
    assert "buy AAPL" not in out and "secret plan" not in out
    assert privacy.MARKER in out               # both free-text fields collapse to the marker
    assert "abcd1234" in out and "idle" in out  # structural fields stay visible


def test_html_shows_content_when_redaction_off():
    cfg = {**config.DEFAULTS, "redact_default": False}
    out = render._row_html(_render_row(last_prompt="visible prompt", custom_title="visible title"), cfg)
    assert "visible prompt" in out and "visible title" in out


def test_serialize_redacts_free_text_but_not_structure(monkeypatch):
    monkeypatch.setattr(config, "load", lambda *a, **k: {**config.DEFAULTS, "redact_default": True})
    row = {"session_id": "s", "u8": "u", "pid": 1, "name": "n", "model": "m", "status": "idle",
           "ctx": 10, "peak_ctx": 0, "win": 200000, "win_certain": True, "cum_input": 0,
           "cum_output": 0, "cum_cache": 0, "full": True, "bridge_id": "", "bridge_short": "-",
           "custom_title": "mytitle", "override_title": "", "last_prompt": "topsecret", "mtime": 1.0}
    s = json.loads(stream.serialize({"rows": [row], "prom": {}}))["sessions"][0]
    assert s["last_prompt"] == privacy.MARKER and s["custom_title"] == privacy.MARKER
    assert s["u8"] == "u" and s["status"] == "idle" and s["ctx"] == 10  # structure intact
