"""Render dashboard rows as a text snapshot or a self-refreshing HTML page."""
from __future__ import annotations

import html as _html
import time

from .collect import title_of

# Context-usage colour thresholds (percent of the window): green < WARN <= amber < CRIT <= red.
CTX_WARN_PCT = 50
CTX_CRIT_PCT = 80
# Display truncation caps (chars). Text and HTML columns have different widths, hence two sets.
TITLE_TRUNC_TEXT = 22
PROMPT_TRUNC_TEXT = 40
TITLE_TRUNC_HTML = 48
PROMPT_TRUNC_HTML = 70

# Strip C0/C1 control chars + DEL so a session's prompt can't inject ANSI escapes (terminal-title
# / clear-screen / colour) into the `once`/`html` output that an operator views in a terminal.
_STRIP = dict.fromkeys(list(range(0x20)) + [0x7F] + list(range(0x80, 0xA0)), None)


def _clean(s) -> str:
    return (s or "").translate(_STRIP)


def fmt_k(n: int) -> str:
    if n >= 1_000_000:  # a 1M window / large cumulative reads cleaner as "1.0M" than "1000.0k"
        return f"{n / 1_000_000:.1f}M"
    return f"{n / 1000:.1f}k" if n >= 1000 else str(n)


def trunc(s: str, n: int) -> str:
    """Sanitize control chars, then cut to n chars with an ellipsis marker when clipped."""
    s = _clean(s)
    return s if len(s) <= n else s[: n - 1] + "…"


def short_model(m) -> str:
    return _clean((m or "-").replace("claude-", ""))


def _idle(idle_s: float) -> str:
    return f"{int(idle_s)}s" if idle_s < 3600 else f"{int(idle_s / 60)}m"


def _ts(epoch: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(epoch))


def render_text(d: dict) -> str:
    prom = d["prom"]
    lines = ["=" * 92, f" cc-monitor   {_ts(d['ts'])}", "=" * 92]
    rc = "connected" if prom.get("rc_connected") == "1" else "DOWN/?"
    lines.append(
        f" cc-session RC: {rc:10s} auth:{'ok' if prom.get('auth_healthy') == '1' else '?':4s} "
        f"workers(scraped):{prom.get('workers', '?')}/{prom.get('capacity', '?')}  "
        f"registry_sessions:{len(d['rows'])}"
    )
    lines.append("-" * 92)
    lines.append(
        f" {'ST':2s} {'UUID8':8s} {'NAME':6s} {'MODEL':11s} {'CONTEXT':>14s} "
        f"{'CUM i/o':>12s} {'IDLE':>5s}  {'TITLE':22s} LAST-PROMPT"
    )
    lines.append("-" * 150)
    for r in d["rows"]:
        win, certain = r["win"], r["win_certain"]
        pct = 100 * r["ctx"] / win if win else 0
        bar = "#" * min(int(pct / 10), 10) + "." * (10 - min(int(pct / 10), 10))
        ctx_s = f"{fmt_k(r['ctx'])}/{fmt_k(win)}{'' if certain else '?'}"
        cum = f"{fmt_k(r['cum_input'])}/{fmt_k(r['cum_output'])}" if r["full"] else "(big)"
        mark = "●" if r["status"] == "busy" else "○"
        title, _src = title_of(r)
        title = trunc(title, TITLE_TRUNC_TEXT) if title else "—"
        lines.append(
            f" {mark} {r['u8']:8s} {_clean(r['name']):6s} {short_model(r['model']):11s} "
            f"{ctx_s:>7s}[{bar}]{pct:3.0f}% {cum:>12s} {_idle(r['idle_s']):>5s}  "
            f"{title:22s} {trunc(r['last_prompt'], PROMPT_TRUNC_TEXT) or '—'}"
        )
    lines.append("-" * 150)
    lines.append(
        " ● busy / ○ idle (registry status; env workers via mtime).  TITLE = custom-title"
        " or manual override; '—' = env-spawned GUI session, real title cloud-side."
    )
    lines.append(
        " ctx = input-side (#27361-safe). window = worker environ [1m] rule + peak lower-bound;"
        " '?' = env unreadable. LAST-PROMPT = last user turn (volatile, not identity)."
    )
    return "\n".join(lines)


def _row_html(r: dict) -> str:
    win, certain = r["win"], r["win_certain"]
    pct = 100 * r["ctx"] / win if win else 0
    winlbl = f"{fmt_k(win)}{'' if certain else '?'}"
    color = "#e5534b" if pct > CTX_CRIT_PCT else "#d9a441" if pct > CTX_WARN_PCT else "#3fb950"
    stat_c = "#3fb950" if r["status"] == "busy" else "#8b949e"
    cum = f"{fmt_k(r['cum_input'])}/{fmt_k(r['cum_output'])}" if r["full"] else "(big)"
    title, src = title_of(r)
    title_html = _html.escape(trunc(title, TITLE_TRUNC_HTML)) if title else "<span style='opacity:.4'>— (cloud-side)</span>"
    lastp = _html.escape(trunc(r["last_prompt"], PROMPT_TRUNC_HTML)) or "—"
    # every dynamic field is control-char-stripped then escaped — name/model/bridge come from
    # registry/transcript (semi-trusted)
    name = _html.escape(_clean(str(r["name"])))
    model = _html.escape(short_model(r["model"]))
    bridge = _html.escape(_clean(str(r["bridge_short"])))
    return (
        f"<tr><td><span style='color:{stat_c}'>● {_html.escape(r['status'])}</span></td>"
        f"<td class=mono>{_html.escape(r['u8'])}</td><td class='mono small'>{name}</td>"
        f"<td>{title_html} <span class=small style='opacity:.5'>[{src}]</span></td>"
        f"<td class='mono small' style='color:#7d8590'>{lastp}</td>"
        f"<td class=mono>{model}</td>"
        f"<td><div class=barwrap><div class=bar style='width:{min(pct, 100):.0f}%;background:{color}'></div></div>"
        f" <span class=small>{fmt_k(r['ctx'])}/{winlbl} ({pct:.0f}%)</span></td>"
        f"<td class=mono>{cum}</td><td>{_idle(r['idle_s'])}</td>"
        f"<td class='mono small'>{bridge}</td></tr>"
    )


def render_html(d: dict, refresh: int = 3) -> str:
    prom = d["prom"]
    rc = "connected" if prom.get("rc_connected") == "1" else "DOWN/?"
    rows = "".join(_row_html(r) for r in d["rows"])
    return f"""<!doctype html><meta charset=utf-8>
<meta http-equiv=refresh content={refresh}>
<link rel=icon href="data:,">
<title>cc-monitor</title>
<style>
 body{{background:#0d1117;color:#c9d1d9;font-family:ui-monospace,Menlo,monospace;padding:18px}}
 h1{{font-size:15px;color:#58a6ff}} .small{{font-size:11px;color:#8b949e}}
 table{{border-collapse:collapse;width:100%;margin-top:10px}}
 th,td{{text-align:left;padding:6px 10px;border-bottom:1px solid #21262d;font-size:13px}}
 th{{color:#8b949e;font-weight:600}} .mono{{font-family:ui-monospace,monospace}}
 .barwrap{{display:inline-block;width:120px;height:8px;background:#21262d;border-radius:4px;vertical-align:middle}}
 .bar{{height:8px;border-radius:4px}}
</style>
<h1>cc-monitor &nbsp;<span class=small>{_ts(d['ts'])} &middot; auto-refresh {refresh}s</span></h1>
<div class=small>cc-session RC: <b>{rc}</b> &middot; auth: <b>{'ok' if prom.get('auth_healthy') == '1' else '?'}</b>
 &middot; workers(scraped): <b>{prom.get('workers', '?')}/{prom.get('capacity', '?')}</b>
 &middot; registry sessions: <b>{len(d['rows'])}</b></div>
<table>
<tr><th>status</th><th>uuid8</th><th>name</th><th>title</th><th>last-prompt</th><th>model</th>
    <th>context (input-side, #27361-safe)</th><th>cum in/out</th><th>idle</th><th>bridge (cloud)</th></tr>
{rows}
</table>
<div class=small style='margin-top:10px'>
 ● busy / ○ idle = registry status (env workers via mtime) &nbsp;|&nbsp;
 title = custom-title or manual override; "— (cloud-side)" = env-spawned GUI session, real title cloud-side &nbsp;|&nbsp;
 window = worker environ [1m] rule + peak lower-bound; "?" = env unreadable</div>
"""
