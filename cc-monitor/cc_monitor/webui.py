"""Single-page dashboard served at ``/``.

The SPA is a Svelte 5 + Vite + Tailwind app (source in ``webui-src/``) built to a SINGLE
self-contained ``index.html`` (JS + CSS inlined by ``vite-plugin-singlefile``) and committed here as
``webui_page.html`` — so the stdlib HTTP server keeps serving ONE static document (offline, no asset
routes, no build step at deploy time; the build runs in dev/CI). It opens ``EventSource('/api/stream')``
and renders the session list client-side, ticking idle locally from each row's ``last_activity_ts``.

Design: docs/plans/cc-monitor-pwa-ui-design.md (seed #1944) — importance-ordered zero-horizontal-
scroll, three density presets, expand-detail, settings drawer, in-place rename (``POST /api/titles``).
XSS-safe by construction: Svelte escapes every ``{text}`` interpolation and the raw-HTML directive is
banned repo-wide (enforced by a source lint in the tests). Free text is redacted server-side in the
payload when ``redact_default`` is on, so there is no raw text to leak client-side (reveal is a server
behaviour switch — D3: single-user, no per-device auth). ``/legacy`` still serves the no-JS fallback.

To rebuild after editing ``webui-src/``: ``cd webui-src && npm ci && npm run build`` (emits this file).
"""
from __future__ import annotations

from pathlib import Path

# The committed build artifact (self-contained HTML). Read once at import as bytes.
_PAGE_BYTES = (Path(__file__).with_name("webui_page.html")).read_bytes()


def spa_page() -> bytes:
    """The static SPA document (constant bytes). Data arrives over ``/api/stream``."""
    return _PAGE_BYTES
