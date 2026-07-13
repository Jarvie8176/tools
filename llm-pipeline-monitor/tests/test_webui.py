"""Source lint on the Svelte frontend — XSS-safety by construction.

Svelte escapes every {text} interpolation; the raw-HTML directive {@html ...} is the one escape
hatch that reintroduces injection. It is banned outright — the payload is numeric-only anyway."""
from __future__ import annotations

from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "webui-src" / "src"


def test_no_raw_html_directive():
    offenders = [p for p in SRC.rglob("*.svelte") if "{@html" in p.read_text(encoding="utf-8")]
    assert not offenders, f"{{@html}} is banned (XSS): {[str(p) for p in offenders]}"


def test_committed_spa_artifact_exists():
    page = SRC.parent.parent / "llm_pipeline_monitor" / "webui_page.html"
    assert page.exists() and page.stat().st_size > 0
