"""Server-side redaction of free-text session fields (prompt + title).

The dashboard renders a session's last prompt and title in the clear — fine on a private,
reverse-proxied host, but a hazard on a shared screen / screenshot / demo. When the
``redact_default`` config knob is on, the server masks those two free-text fields to a fixed
marker **before** they leave the process: they are absent from the rendered HTML, the text
snapshot, AND the API/SSE payload. This is a safe-by-default posture, not obfuscation — the
content is never serialized, so there is nothing to un-blur client-side (a per-viewer reveal
would be an authenticated server round-trip, tracked for M-C).

Only free-text fields are masked. Structural fields (uuid8, name, model, status, token counts,
bridge id) are non-sensitive and stay visible so the dashboard is still useful while redacted.
An empty field (e.g. a cloud-side title) stays empty so its "—" placeholder still renders.
"""
from __future__ import annotations

MARKER = "[redacted]"  # fixed, content-and-length independent — leaks neither text nor its size


def redact(text, on: bool) -> str:
    """Return ``MARKER`` for non-empty ``text`` when ``on``; otherwise ``text`` unchanged.

    Length-independent on purpose: masking to ``"•" * len(text)`` would leak the prompt's size
    (a weak signal, but free to avoid). Empty stays empty so the caller's own "—" fallback wins.
    """
    if on and text:
        return MARKER
    return text
