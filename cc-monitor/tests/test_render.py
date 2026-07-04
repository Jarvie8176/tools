from cc_monitor import render


def test_fmt_k_scales_to_millions():
    # a 1M window reads as "1.0M", not "1000.0k"
    assert render.fmt_k(1_000_000) == "1.0M"
    assert render.fmt_k(1_500_000) == "1.5M"


def test_fmt_k_thousands_and_units():
    assert render.fmt_k(64_700) == "64.7k"
    assert render.fmt_k(999) == "999"


def test_html_inlines_empty_favicon_to_suppress_request():
    # browser must not fetch /favicon.ico (which the server would otherwise 204) on every refresh
    d = {"ts": 0, "prom": {}, "rows": []}
    assert 'rel=icon href="data:,"' in render.render_html(d)
