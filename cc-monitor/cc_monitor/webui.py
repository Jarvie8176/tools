"""Single-page dashboard served at ``/``. A static shell (no per-request ``collect()``) whose JS
opens ``EventSource('/api/stream')`` and renders the session table client-side: rows are patched
in place on each push (no full-page reload), and the idle *duration* is ticked locally from each
row's ``last_activity_ts`` so the clock advances between server pushes without a wasted round-trip.

This replaces the ``<meta refresh>`` server-rendered page (still available at ``/legacy`` for
curl / no-JS). Free-text (title/prompts) is redacted server-side in the payload when
``redact_default`` is on, so the client only ever displays what it is allowed to — there is no
raw text to leak here. All dynamic text is written via ``textContent`` / ``createElement`` (never
``innerHTML``), so a hostile session name/prompt cannot inject markup.
"""
from __future__ import annotations

# Static document — no f-string (the JS/CSS use literal ``{}``). Served as a constant; the page
# carries no data, it subscribes to /api/stream for everything.
_PAGE = r"""<!doctype html><html lang=en><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<link rel=icon href="data:,">
<title>cc-monitor</title>
<style>
 :root{color-scheme:dark}
 body{background:#0d1117;color:#c9d1d9;font-family:ui-monospace,Menlo,monospace;margin:0;padding:16px}
 h1{font-size:15px;color:#58a6ff;margin:0 0 6px}
 .small{font-size:11px;color:#8b949e}
 .bar-row{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin:8px 0}
 input,select{background:#161b22;color:#c9d1d9;border:1px solid #30363d;border-radius:6px;padding:4px 8px;font:inherit;font-size:12px}
 #conn{font-size:11px;padding:2px 8px;border-radius:10px}
 .up{background:#12261a;color:#3fb950}.down{background:#2d1618;color:#e5534b}
 table{border-collapse:collapse;width:100%;margin-top:8px}
 th,td{text-align:left;padding:6px 10px;border-bottom:1px solid #21262d;font-size:13px;white-space:nowrap}
 th{color:#8b949e;font-weight:600;cursor:pointer;user-select:none}
 td.wrap,th.wrap{white-space:normal}
 .mono{font-family:ui-monospace,monospace}
 .barwrap{display:inline-block;width:110px;height:8px;background:#21262d;border-radius:4px;vertical-align:middle}
 .bar{height:8px;border-radius:4px}
 tr.busy td:first-child{border-left:2px solid #3fb950}
 .dim{opacity:.4}
 footer{margin-top:10px}
</style>
<h1>cc-monitor <span class=small id=meta></span></h1>
<div class=small id=header></div>
<div class=bar-row>
 <span id=conn class=down>connecting…</span>
 <input id=filter placeholder="filter name / title / prompt / model / uuid" size=34>
 <label class=small>sort
  <select id=sort>
   <option value=default>busy, then recent</option>
   <option value=context>context %</option>
   <option value=idle>idle</option>
   <option value=name>name</option>
  </select>
 </label>
 <label class=small><input type=checkbox id=groupbridge> group bridged</label>
 <span class=small id=count></span>
</div>
<table>
 <thead><tr>
  <th data-sort=default>status</th><th>uuid8</th><th>name</th><th class=wrap>title</th>
  <th class=wrap>initial-prompt</th><th class=wrap>last-prompt</th><th>model</th><th>s-effort</th>
  <th data-sort=context>context</th><th>cum in/out</th><th data-sort=idle>idle</th><th>bridge</th>
 </tr></thead>
 <tbody id=rows></tbody>
</table>
<footer class=small>
 ● busy = generating / ◐ active = registered, reachable / ⚠ orphaned = present but not reachable
 &nbsp;|&nbsp; title = custom-title or manual override; "— (cloud-side)" = env-spawned GUI session
 &nbsp;|&nbsp; initial-prompt = opening turn (stable) / last-prompt = latest (volatile)
 &nbsp;|&nbsp; context = input-side (#27361-safe); window "?" = env unreadable
 &nbsp;|&nbsp; idle ticks locally from last activity
</footer>
<script>
"use strict";
// --- formatting (mirrors render.py: fmt_k / short_model / _idle / title_of / glyph) -------------
const WARN = {warn: 70, crit: 85};                 // ctx colour thresholds; refreshed from /api/config
function fmtK(n){ n = n||0;
  if (n >= 1e6) return (n/1e6).toFixed(1)+"M";
  return n >= 1000 ? (n/1000).toFixed(1)+"k" : String(n); }
function shortModel(m){ return (m||"-").replace("claude-",""); }
function fmtIdle(s){ s = Math.max(0, Math.floor(s)); return s < 3600 ? s+"s" : Math.floor(s/60)+"m"; }
function titleOf(r){                                // override > custom-title > cloud-side
  if (r.override_title) return {t: r.override_title, src: "override"};
  if (r.custom_title)   return {t: r.custom_title,   src: "custom"};
  return {t: "", src: "cloud-side"}; }
function glyph(st){ return st==="orphaned" ? "⚠" : st==="busy" ? "●" : "◐"; }
function statusColor(st){ return st==="orphaned" ? "#e5534b" : st==="busy" ? "#3fb950" : "#8b949e"; }

// --- state --------------------------------------------------------------------------------------
let SESSIONS = [];                                  // latest payload rows
const ROWS = new Map();                             // session_id -> <tr> (patched in place)
const tbody = document.getElementById("rows");
const $ = (id) => document.getElementById(id);

function cell(tr, cls){ const td = document.createElement("td"); if (cls) td.className = cls; tr.appendChild(td); return td; }
function mkRow(){
  const tr = document.createElement("tr");
  tr._c = {
    status: cell(tr), u8: cell(tr, "mono"), name: cell(tr, "mono small"), title: cell(tr, "wrap"),
    initp: cell(tr, "mono small dim"), lastp: cell(tr, "mono small dim"), model: cell(tr, "mono"),
    seff: cell(tr), ctx: cell(tr), cum: cell(tr, "mono"), idle: cell(tr), bridge: cell(tr, "mono small"),
  };
  return tr;
}
function setText(td, s){ if (td.textContent !== s) td.textContent = s; }   // patch only on change

function paintCtx(td, r){
  const win = r.win || 0, pct = win ? 100*r.ctx/win : 0;
  const color = pct > WARN.crit ? "#e5534b" : pct > WARN.warn ? "#d9a441" : "#3fb950";
  td.textContent = "";                              // rebuild: a styled bar + a label (no user text)
  const wrap = document.createElement("span"); wrap.className = "barwrap";
  const bar = document.createElement("span"); bar.className = "bar";
  bar.style.width = Math.min(pct, 100).toFixed(0)+"%"; bar.style.background = color;
  wrap.appendChild(bar);
  const lbl = document.createElement("span"); lbl.className = "small";
  lbl.textContent = " " + fmtK(r.ctx) + "/" + fmtK(win) + (r.win_certain ? "" : "?") + " (" + pct.toFixed(0) + "%)";
  td.appendChild(wrap); td.appendChild(lbl);
}
function paintRow(tr, r){
  const c = tr._c, ti = titleOf(r);
  tr.className = r.status === "busy" ? "busy" : "";
  const g = c.status; g.textContent = glyph(r.status) + " " + r.status; g.style.color = statusColor(r.status);
  setText(c.u8, r.u8 || ""); setText(c.name, r.name || "-");
  c.title.textContent = "";
  const ts = document.createElement("span");
  if (ti.t){ ts.textContent = ti.t; } else { ts.textContent = "— (cloud-side)"; ts.className = "dim"; }
  const tsrc = document.createElement("span"); tsrc.className = "small dim"; tsrc.textContent = " [" + ti.src + "]";
  c.title.appendChild(ts); c.title.appendChild(tsrc);
  setText(c.initp, r.initial_prompt || "—"); setText(c.lastp, r.last_prompt || "—");
  setText(c.model, shortModel(r.model));
  setText(c.seff, r.session_effort || "·"); c.seff.className = r.session_effort ? "mono" : "small dim";
  paintCtx(c.ctx, r);
  setText(c.cum, r.full ? (fmtK(r.cum_input) + "/" + fmtK(r.cum_output)) : "(big)");
  tickIdle(tr, r);
  setText(c.bridge, r.bridge_short && r.bridge_short !== "-" ? r.bridge_short : "");
}
function tickIdle(tr, r){                            // local idle-duration tick (no server push)
  const ts = r.last_activity_ts || 0;
  setText(tr._c.idle, ts ? fmtIdle(Date.now()/1000 - ts) : "—");
}

// --- ordering + filtering (client-side) ---------------------------------------------------------
function visible(){
  const q = $("filter").value.trim().toLowerCase();
  let rows = SESSIONS.filter(r => !q || [r.name, r.custom_title, r.override_title, r.initial_prompt,
      r.last_prompt, r.model, r.u8].some(v => (v||"").toLowerCase().includes(q)));
  const mode = $("sort").value;
  const cmp = {
    context: (a,b) => (b.ctx/(b.win||1)) - (a.ctx/(a.win||1)),
    idle:    (a,b) => (b.last_activity_ts||0) - (a.last_activity_ts||0),   // most-recent first
    name:    (a,b) => (a.name||"").localeCompare(b.name||""),
    default: (a,b) => (a.status!=="busy") - (b.status!=="busy") || (b.last_activity_ts||0) - (a.last_activity_ts||0),
  }[mode] || (()=>0);
  rows = rows.slice().sort(cmp);
  if ($("groupbridge").checked)                      // stable partition: bridged rows first
    rows = rows.slice().sort((a,b) => (!a.bridge_id) - (!b.bridge_id));
  return rows;
}
function reconcile(){
  const rows = visible(), keep = new Set();
  rows.forEach((r, i) => {
    let tr = ROWS.get(r.session_id);
    if (!tr){ tr = mkRow(); ROWS.set(r.session_id, tr); }
    paintRow(tr, r);
    if (tbody.children[i] !== tr) tbody.insertBefore(tr, tbody.children[i] || null);  // move into order
    keep.add(r.session_id);
  });
  for (const [id, tr] of ROWS) if (!keep.has(id)){ tr.remove(); ROWS.delete(id); }   // drop gone sessions
  $("count").textContent = rows.length + " shown / " + SESSIONS.length + " sessions";
}

// --- header (effort + cc-session RC / standalone) -----------------------------------------------
function paintHeader(d){
  $("meta").textContent = "effort " + (d.effort || "?");
  const p = d.prom || {}, h = $("header");
  if (d.cc_session){
    const rc = p.rc_connected === "1" ? "connected" : "DOWN/?";
    h.textContent = "cc-session RC: " + rc + " · auth: " + (p.auth_healthy === "1" ? "ok" : "?")
      + " · workers(scraped): " + (p.workers ?? "?") + "/" + (p.capacity ?? "?")
      + " · registry sessions: " + SESSIONS.length;
  } else {
    h.textContent = "registry sessions: " + SESSIONS.length + " · standalone (no cc-session supervisor)";
  }
}

// --- transport ----------------------------------------------------------------------------------
function apply(d){ SESSIONS = d.sessions || []; paintHeader(d); reconcile(); }
function setConn(up){ const e = $("conn"); e.textContent = up ? "live" : "reconnecting…"; e.className = up ? "up" : "down"; }
function connect(){
  const es = new EventSource("/api/stream");
  es.onopen = () => setConn(true);
  es.onmessage = (e) => { setConn(true); try { apply(JSON.parse(e.data)); } catch (_){} };
  es.onerror = () => setConn(false);                 // EventSource auto-reconnects; just reflect state
}
fetch("/api/config").then(r => r.json()).then(c => {  // pick up runtime ctx colour thresholds
  if (typeof c.ctx_warn_pct === "number") WARN.warn = c.ctx_warn_pct;
  if (typeof c.ctx_crit_pct === "number") WARN.crit = c.ctx_crit_pct;
}).catch(()=>{});
["input","change"].forEach(ev => { $("filter").addEventListener(ev, reconcile); $("sort").addEventListener(ev, reconcile); });
$("groupbridge").addEventListener("change", reconcile);
document.querySelectorAll("th[data-sort]").forEach(th =>
  th.addEventListener("click", () => { $("sort").value = th.dataset.sort; reconcile(); }));
setInterval(() => { for (const [id, tr] of ROWS){ const r = SESSIONS.find(s => s.session_id === id); if (r) tickIdle(tr, r); } }, 1000);
connect();
</script>
</html>
"""

_PAGE_BYTES = _PAGE.encode("utf-8")


def spa_page() -> bytes:
    """The static SPA document (constant bytes). Data arrives over ``/api/stream``."""
    return _PAGE_BYTES
