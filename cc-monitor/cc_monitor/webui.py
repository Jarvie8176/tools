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

import base64
import json
from pathlib import Path

# The committed build artifact (self-contained HTML). Read once at import as bytes.
_PAGE_BYTES = (Path(__file__).with_name("webui_page.html")).read_bytes()


def spa_page() -> bytes:
    """The static SPA document (constant bytes). Data arrives over ``/api/stream``."""
    return _PAGE_BYTES


# ── PWA install manifest (manifest-only, no service worker) ──────────────────────────────────
# Makes the dashboard "add to home screen" installable as a standalone-window app. No offline
# service worker: this is a tailnet localhost panel with no offline need, and the shell already
# revalidates every load (Cache-Control: no-cache), so a SW cache would add version-staleness risk
# without benefit. The icon is an inline SVG data-URI so the app stays self-contained (no asset
# routes / committed binaries); `sizes: any` covers install prompts that want 192/512.
_ICON_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">'
    '<rect width="512" height="512" rx="96" fill="#0d1218"/>'
    '<circle cx="256" cy="176" r="42" fill="#3fb950"/>'
    '<text x="256" y="392" font-family="ui-monospace,monospace" font-size="210" '
    'font-weight="700" fill="#e6edf3" text-anchor="middle">cc</text>'
    "</svg>"
)
_ICON_URI = "data:image/svg+xml;base64," + base64.b64encode(_ICON_SVG.encode()).decode()
_MANIFEST_BYTES = json.dumps(
    {
        "name": "cc-monitor — Claude Code sessions",
        "short_name": "cc-monitor",
        "description": "Live Claude Code session dashboard (model / token / context / status).",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "background_color": "#05070a",
        "theme_color": "#0d1218",
        "icons": [{"src": _ICON_URI, "sizes": "any", "type": "image/svg+xml", "purpose": "any"}],
    },
    separators=(",", ":"),
).encode()


def manifest() -> bytes:
    """The PWA web app manifest (constant bytes), served at ``/manifest.webmanifest``."""
    return _MANIFEST_BYTES
