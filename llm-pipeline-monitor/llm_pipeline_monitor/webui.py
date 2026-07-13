"""Single-page dashboard served at ``/``.

The SPA is a Svelte 5 + Vite + Tailwind app (source in ``webui-src/``) built to a SINGLE
self-contained ``index.html`` (JS + CSS inlined by ``vite-plugin-singlefile``) and committed here as
``webui_page.html`` — so the stdlib HTTP server keeps serving ONE static document (offline, no asset
routes, no build step at deploy time; the build runs in dev/CI). It opens ``EventSource('/api/stream')``
and renders the endpoint list client-side.

XSS-safe by construction: Svelte escapes every ``{text}`` interpolation and the raw-HTML directive is
banned (enforced by a source lint in the tests). The payload carries only numeric metrics + a served
model path (no free-text user content), so there is nothing sensitive to leak client-side.

To rebuild after editing ``webui-src/``: ``cd webui-src && npm ci && npm run build`` (emits this file).
"""
from __future__ import annotations

from pathlib import Path

# The committed build artifact (self-contained HTML). Read once at import as bytes.
_PAGE_BYTES = (Path(__file__).with_name("webui_page.html")).read_bytes()


def spa_page() -> bytes:
    """The static SPA document (constant bytes). Data arrives over ``/api/stream``."""
    return _PAGE_BYTES
