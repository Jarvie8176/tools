from cc_monitor import render


def test_fmt_k_scales_to_millions():
    # a 1M window reads as "1.0M", not "1000.0k"
    assert render.fmt_k(1_000_000) == "1.0M"
    assert render.fmt_k(1_500_000) == "1.5M"


def test_fmt_k_thousands_and_units():
    assert render.fmt_k(64_700) == "64.7k"
    assert render.fmt_k(999) == "999"


def test_ctx_colour_respects_named_thresholds():
    # green below WARN, amber between WARN and CRIT, red above CRIT — driven by the constants
    def colour(pct):
        win = 100_000
        row = {"ctx": int(pct / 100 * win), "win": win, "win_certain": True, "status": "idle",
               "cum_input": 0, "cum_output": 0, "full": True, "idle_s": 1, "name": "n",
               "model": "m", "bridge_short": "-", "u8": "abcd1234", "last_prompt": "",
               "override_title": "", "custom_title": ""}
        return render._row_html(row)
    assert "#3fb950" in colour(render.CTX_WARN_PCT - 1)   # green
    assert "#d9a441" in colour(render.CTX_WARN_PCT + 1)   # amber
    assert "#e5534b" in colour(render.CTX_CRIT_PCT + 1)   # red


def test_html_inlines_empty_favicon_to_suppress_request():
    # browser must not fetch /favicon.ico (which the server would otherwise 204) on every refresh
    d = {"ts": 0, "prom": {}, "rows": []}
    assert 'rel=icon href="data:,"' in render.render_html(d)
