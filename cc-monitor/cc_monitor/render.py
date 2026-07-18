"""Render dashboard rows as a text snapshot or a self-refreshing HTML page."""
from __future__ import annotations

import html as _html
import time

from . import config, privacy
from .collect import title_of

# Colour thresholds (ctx_warn/crit_pct) and truncation caps (title/prompt_trunc_text/html) are
# runtime-configurable — see cc_monitor.config. Read live at render time so a UI/API edit applies
# on the next refresh.

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


def disp_model(r: dict) -> str:
    """Display label for a row's model: the operator alias if set, else the shortened raw id.

    Display-only — the raw ``model`` field is never rewritten (it stays the join/metrics key). Keeps
    every render path (text / static HTML / legacy) consistent with the SPA, which prefers the alias.
    """
    alias = r.get("model_alias")
    return _clean(alias) if alias else short_model(r.get("model"))


def _idle(idle_s: float) -> str:
    return f"{int(idle_s)}s" if idle_s < 3600 else f"{int(idle_s / 60)}m"


_ORIGIN_ABBR = {"cc-session-managed": "mgd", "rc-env-spawned": "env", "individual-cli": "cli"}


def _origin_abbr(origin) -> str:
    return _ORIGIN_ABBR.get(origin, "?")


def _recon(recon: dict) -> str:
    """One-line reconciliation falloff across the independent population signals. The
    drift between columns is the point — `scraped` (unreliable) vs the registry is the alert."""
    if not recon:
        return ""
    sc = recon.get("scraped")
    return (f"recon: registry {recon.get('registry', 0)} · managed {recon.get('managed', 0)}"
            f" · env-spawned {recon.get('rc_env_spawned', 0)} · individual {recon.get('individual_cli', 0)}"
            f" · bridged {recon.get('bridged', 0)} · url-ledger {recon.get('url_ledger', 0)}"
            f" · scraped {sc if sc is not None else '—'}")


def _glyph(status: str) -> str:
    """Status glyph, shared by the text and HTML renderers so 'active' never scans like 'busy'."""
    return "⚠" if status == "orphaned" else "●" if status == "busy" else "◐"


def _ts(epoch: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(epoch))


def render_text(d: dict) -> str:
    cfg = config.load()
    prom = d["prom"]
    effort = _clean(d.get("effort") or "?")
    lines = ["=" * 92, f" cc-monitor   {_ts(d['ts'])}   effort:{effort}", "=" * 92]
    if d.get("cc_session"):  # optional enrichment — only when the supervisor is on THIS host
        rc = "connected" if prom.get("rc_connected") == "1" else "DOWN/?"
        lines.append(
            f" cc-session RC: {rc:10s} auth:{'ok' if prom.get('auth_healthy') == '1' else '?':4s} "
            f"workers(scraped):{prom.get('workers', '?')}/{prom.get('capacity', '?')}  "
            f"registry_sessions:{len(d['rows'])}"
        )
    else:  # standalone: no cc-session here — show the registry count, not a misleading "RC DOWN"
        lines.append(f" registry_sessions:{len(d['rows'])}   (standalone — no cc-session supervisor)")
    recon = _recon(d.get("recon", {}))
    if recon:
        lines.append(" " + recon)
    lines.append("-" * 92)
    pw = cfg["prompt_trunc_text"]
    lines.append(
        f" {'ST':2s} {'UUID8':8s} {'NAME':6s} {'ORIG':4s} {'MODEL':11s} {'EFF':6s} {'CONTEXT':>14s} "
        f"{'CUM i/o':>12s} {'IDLE':>5s}  {'TITLE':22s} {'INIT-PROMPT'.ljust(pw)} LAST-PROMPT"
    )
    lines.append("-" * 150)
    for r in d["rows"]:
        win, certain = r["win"], r["win_certain"]
        pct = 100 * r["ctx"] / win if win else 0
        bar = "#" * min(int(pct / 10), 10) + "." * (10 - min(int(pct / 10), 10))
        ctx_s = f"{fmt_k(r['ctx'])}/{fmt_k(win)}{'' if certain else '?'}"
        cum = f"{fmt_k(r['cum_input'])}/{fmt_k(r['cum_output'])}" if r["full"] else "(big)"
        mark = _glyph(r["status"])
        redact_on = cfg["redact_default"]
        title, _src = title_of(r)
        title = privacy.redact(title, redact_on)
        title = trunc(title, cfg["title_trunc_text"]) if title else "—"
        initp = (trunc(privacy.redact(r.get("initial_prompt"), redact_on), pw) or "—").ljust(pw)
        lastp = trunc(privacy.redact(r["last_prompt"], redact_on), pw) or "—"
        seff = trunc(r.get("session_effort") or "·", 6)  # per-session effort (OTel); '·' = no data
        lines.append(
            f" {mark} {r['u8']:8s} {_clean(r['name']):6s} {_origin_abbr(r.get('origin')):4s} "
            f"{disp_model(r):11s} "
            f"{seff:6s} {ctx_s:>7s}[{bar}]{pct:3.0f}% {cum:>12s} {_idle(r['idle_s']):>5s}  "
            f"{title:22s} {initp} {lastp}"
        )
    lines.append("-" * 150)
    lines.append(
        " ● busy (generating) / ◐ active (registered = reachable connection) / ⚠ orphaned (present, not reachable)."
        "  TITLE = custom-title"
        " or manual override; '—' = env-spawned GUI session, real title cloud-side."
    )
    lines.append(
        " ctx = input-side (#27361-safe). window = worker environ [1m] rule + peak lower-bound;"
        " '?' = env unreadable. INIT-PROMPT = opening user turn (stable); LAST-PROMPT = last user"
        " turn (volatile). header effort = settings.json effortLevel (global; '?' = unreadable);"
        " EFF col = per-session effort from OTel (latest request; '·' = telemetry off/no data)."
    )
    return "\n".join(lines)


def _row_html(r: dict, cfg: dict | None = None) -> str:
    cfg = cfg or config.load()
    win, certain = r["win"], r["win_certain"]
    pct = 100 * r["ctx"] / win if win else 0
    winlbl = f"{fmt_k(win)}{'' if certain else '?'}"
    color = "#e5534b" if pct > cfg["ctx_crit_pct"] else "#d9a441" if pct > cfg["ctx_warn_pct"] else "#3fb950"
    stat_c = "#e5534b" if r["status"] == "orphaned" else "#3fb950" if r["status"] == "busy" else "#8b949e"
    cum = f"{fmt_k(r['cum_input'])}/{fmt_k(r['cum_output'])}" if r["full"] else "(big)"
    redact_on = cfg["redact_default"]
    title, src = title_of(r)
    title = privacy.redact(title, redact_on)
    title_html = _html.escape(trunc(title, cfg["title_trunc_html"])) if title else "<span style='opacity:.4'>— (cloud-side)</span>"
    pw = cfg["prompt_trunc_html"]
    initp = _html.escape(trunc(privacy.redact(r.get("initial_prompt"), redact_on), pw)) or "—"
    lastp = _html.escape(trunc(privacy.redact(r["last_prompt"], redact_on), pw)) or "—"
    # every dynamic field is control-char-stripped then escaped — name/model/bridge come from
    # registry/transcript (semi-trusted)
    name = _html.escape(_clean(str(r["name"])))
    model = _html.escape(disp_model(r))
    bridge = _html.escape(_clean(str(r["bridge_short"])))
    seff = r.get("session_effort")
    seff_html = (f"<span class=mono>{_html.escape(trunc(seff, 8))}</span>" if seff
                 else "<span class=small style='opacity:.4'>·</span>")
    return (
        f"<tr><td><span style='color:{stat_c}'>{_glyph(r['status'])} {_html.escape(r['status'])}</span></td>"
        f"<td class=mono>{_html.escape(r['u8'])}</td><td class='mono small'>{name}</td>"
        f"<td class=small title='{_html.escape(str(r.get('origin') or ''))}'>{_origin_abbr(r.get('origin'))}"
        f"{' ·b' if r.get('bridged') else ''}</td>"
        f"<td>{title_html} <span class=small style='opacity:.5'>[{src}]</span></td>"
        f"<td class='mono small' style='color:#7d8590'>{initp}</td>"
        f"<td class='mono small' style='color:#7d8590'>{lastp}</td>"
        f"<td class=mono>{model}</td>"
        f"<td>{seff_html}</td>"
        f"<td><div class=barwrap><div class=bar style='width:{min(pct, 100):.0f}%;background:{color}'></div></div>"
        f" <span class=small>{fmt_k(r['ctx'])}/{winlbl} ({pct:.0f}%)</span></td>"
        f"<td class=mono>{cum}</td><td>{_idle(r['idle_s'])}</td>"
        f"<td class='mono small'>{bridge}</td></tr>"
    )


def render_html(d: dict, refresh: int = 3) -> str:
    cfg = config.load()
    prom = d["prom"]
    n = len(d["rows"])
    if d.get("cc_session"):  # optional enrichment — only when the supervisor is on THIS host
        rc = "connected" if prom.get("rc_connected") == "1" else "DOWN/?"
        header = (
            f"cc-session RC: <b>{rc}</b> &middot; auth: <b>{'ok' if prom.get('auth_healthy') == '1' else '?'}</b>"
            f" &middot; workers(scraped): <b>{prom.get('workers', '?')}/{prom.get('capacity', '?')}</b>"
            f" &middot; registry sessions: <b>{n}</b>"
        )
    else:  # standalone: no cc-session here — don't imply a broken RC
        header = f"registry sessions: <b>{n}</b> &middot; <span style='opacity:.6'>standalone (no cc-session supervisor)</span>"
    effort = _html.escape(_clean(d.get("effort") or "?"))
    rows = "".join(_row_html(r, cfg) for r in d["rows"])
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
<h1>cc-monitor &nbsp;<span class=small>{_ts(d['ts'])} &middot; auto-refresh {refresh}s &middot; effort {effort}</span></h1>
<div class=small>{header}</div>
<div class=small style='margin-top:4px'>{_html.escape(_recon(d.get('recon', {})))}</div>
<table>
<tr><th>status</th><th>uuid8</th><th>name</th><th>origin</th><th>title</th><th>initial-prompt</th><th>last-prompt</th><th>model</th><th>s-effort</th>
    <th>context (input-side, #27361-safe)</th><th>cum in/out</th><th>idle</th><th>bridge (cloud)</th></tr>
{rows}
</table>
<div class=small style='margin-top:10px'>
 ● busy = generating / ◐ active = registered, reachable connection / ⚠ orphaned = present but not reachable &nbsp;|&nbsp;
 title = custom-title or manual override; "— (cloud-side)" = env-spawned GUI session, real title cloud-side &nbsp;|&nbsp;
 initial-prompt = opening user turn (stable) / last-prompt = latest (volatile) &nbsp;|&nbsp;
 header effort = settings.json effortLevel (global; "?" = unreadable); s-effort = per-session effort from OTel (latest request; "·" = telemetry off/no data) &nbsp;|&nbsp;
 window = worker environ [1m] rule + peak lower-bound; "?" = env unreadable</div>
"""
