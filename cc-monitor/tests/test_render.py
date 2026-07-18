from cc_monitor import render


def test_fmt_k_scales_to_millions():
    # a 1M window reads as "1.0M", not "1000.0k"
    assert render.fmt_k(1_000_000) == "1.0M"
    assert render.fmt_k(1_500_000) == "1.5M"


def test_fmt_k_thousands_and_units():
    assert render.fmt_k(64_700) == "64.7k"
    assert render.fmt_k(999) == "999"


def test_ctx_colour_respects_config_thresholds():
    # green below WARN, amber between WARN and CRIT, red above CRIT — driven by config thresholds
    from cc_monitor import config
    warn, crit = config.DEFAULTS["ctx_warn_pct"], config.DEFAULTS["ctx_crit_pct"]

    def colour(pct):
        win = 100_000
        row = {"ctx": int(pct / 100 * win), "win": win, "win_certain": True, "status": "active",
               "cum_input": 0, "cum_output": 0, "full": True, "idle_s": 1, "name": "n",
               "model": "m", "bridge_short": "-", "u8": "abcd1234", "last_prompt": "",
               "override_title": "", "custom_title": ""}
        return render._row_html(row, config.DEFAULTS)  # explicit cfg -> hermetic (no file read)
    assert "#3fb950" in colour(warn - 1)   # green
    assert "#d9a441" in colour(warn + 1)   # amber
    assert "#e5534b" in colour(crit + 1)   # red


def test_html_status_glyph_distinguishes_active_from_busy():
    from cc_monitor import config

    def row_html(status):
        row = {"ctx": 0, "win": 100000, "win_certain": True, "status": status, "cum_input": 0,
               "cum_output": 0, "full": True, "idle_s": 1, "name": "n", "model": "m",
               "bridge_short": "-", "u8": "abcd1234", "last_prompt": "", "override_title": "",
               "custom_title": ""}
        return render._row_html(row, config.DEFAULTS)
    assert "● busy" in row_html("busy")
    assert "◐ active" in row_html("active") and "● active" not in row_html("active")  # not busy glyph
    assert "⚠ orphaned" in row_html("orphaned")


def test_html_inlines_empty_favicon_to_suppress_request():
    # browser must not fetch /favicon.ico (which the server would otherwise 204) on every refresh
    d = {"ts": 0, "prom": {}, "rows": []}
    assert 'rel=icon href="data:,"' in render.render_html(d)


def test_standalone_omits_cc_session_header_no_misleading_rc_down():
    # cc-session absent -> no "cc-session RC" line; show a standalone marker instead of "RC DOWN"
    d = {"ts": 0, "prom": {}, "rows": [], "cc_session": False}
    text, html = render.render_text(d), render.render_html(d)
    assert "cc-session RC" not in text and "DOWN" not in text and "standalone" in text
    assert "cc-session RC" not in html and "standalone" in html


def test_effort_shown_in_headers():
    d = {"ts": 0, "prom": {}, "rows": [], "effort": "high"}
    assert "effort:high" in render.render_text(d)
    assert "effort high" in render.render_html(d)


def test_effort_unknown_renders_placeholder():
    # effort absent (settings unreadable) -> '?' placeholder, not a crash or "None"
    d = {"ts": 0, "prom": {}, "rows": []}
    assert "effort:?" in render.render_text(d)
    assert "effort ?" in render.render_html(d)


def test_initial_prompt_rendered_in_row():
    row = {"ctx": 0, "win": 100000, "win_certain": True, "status": "active", "cum_input": 0,
           "cum_output": 0, "full": True, "idle_s": 1, "name": "n", "model": "m",
           "bridge_short": "-", "u8": "abcd1234", "last_prompt": "later turn",
           "initial_prompt": "opening turn", "override_title": "", "custom_title": ""}
    html = render._row_html(row, {**config_defaults(), "redact_default": False})
    assert "opening turn" in html and "later turn" in html


def _row(**kw):
    base = {"ctx": 0, "win": 100000, "win_certain": True, "status": "active", "cum_input": 0,
            "cum_output": 0, "full": True, "idle_s": 1, "name": "n", "model": "m",
            "bridge_short": "-", "u8": "abcd1234", "last_prompt": "", "initial_prompt": "",
            "override_title": "", "custom_title": ""}
    base.update(kw)
    return base


def test_session_effort_rendered_in_row_html():
    html = render._row_html(_row(session_effort="xhigh"), config_defaults())
    assert "xhigh" in html


def test_session_effort_placeholder_when_absent_html():
    # no per-session effort (telemetry off / no data) -> a dim '·', never "None"
    html = render._row_html(_row(session_effort=None), config_defaults())
    assert "None" not in html and "·" in html


def test_session_effort_in_text_row():
    d = {"ts": 0, "prom": {}, "rows": [_row(session_effort="max")], "effort": "high"}
    out = render.render_text(d)
    assert "max" in out and "effort:high" in out  # per-session col AND global header coexist


def test_session_effort_html_escaped():
    # OTel value is semi-trusted; a hostile effort string must be escaped, not injected
    html = render._row_html(_row(session_effort="<img src=x>"), config_defaults())
    assert "<img src=x>" not in html and "&lt;img" in html


def config_defaults():
    from cc_monitor import config
    return config.DEFAULTS


def test_cc_session_header_shown_when_supervisor_present():
    d = {"ts": 0, "rows": [], "cc_session": True,
         "prom": {"rc_connected": "1", "auth_healthy": "1", "workers": "3", "capacity": "8"}}
    assert "cc-session RC: connected" in render.render_text(d)
    assert "cc-session RC:" in render.render_html(d) and "standalone" not in render.render_html(d)


def _base_row(**over):
    row = {"ctx": 0, "win": 200000, "win_certain": True, "win_source": "evidence", "status": "active",
           "cum_input": 0, "cum_output": 0, "full": True, "idle_s": 1, "name": "n",
           "model": "claude-opus-4-8", "model_alias": "", "bridge_short": "-", "u8": "abcd1234",
           "origin": "individual-cli", "session_effort": None, "peak_ctx": 0,
           "last_prompt": "", "initial_prompt": "", "override_title": "", "custom_title": ""}
    row.update(over)
    return row


def test_disp_model_prefers_alias_else_short():
    assert render.disp_model(_base_row(model_alias="Opus-Big")) == "Opus-Big"
    assert render.disp_model(_base_row()) == "opus-4-8"           # alias empty -> shortened raw id


def test_disp_model_suppresses_alias_under_redaction():
    # alias is operator free text -> hidden when redacting; fall back to the non-sensitive raw id
    assert render.disp_model(_base_row(model_alias="Secret"), redact=True) == "opus-4-8"


def test_html_render_shows_alias_when_not_redacting_keeps_raw_model():
    from cc_monitor import config
    cfg = {**config.DEFAULTS, "redact_default": False}
    r = _base_row(model_alias="MyOpus")
    html = render._row_html(r, cfg)
    assert "MyOpus" in html                                       # alias shown when reveal on
    assert r["model"] == "claude-opus-4-8"                        # raw field untouched (join/key)


def test_html_render_hides_alias_under_redaction():
    from cc_monitor import config
    cfg = {**config.DEFAULTS, "redact_default": True}
    html = render._row_html(_base_row(model_alias="Secret"), cfg)
    assert "Secret" not in html and "opus-4-8" in html           # masked -> raw model id instead
