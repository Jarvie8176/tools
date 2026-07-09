"""Single-page dashboard served at ``/``. A static shell (no per-request ``collect()``) whose JS
opens ``EventSource('/api/stream')`` and renders the session list client-side: rows/cards are
patched from each push (no full-page reload), and the idle *duration* is ticked locally from each
row's ``last_activity_ts`` so the clock advances between server pushes without a wasted round-trip.

Design (docs/plans/cc-monitor-pwa-ui-design.md, seed #1944): importance-ordered, zero-horizontal-
scroll — any viewport shows 5 fields (status → name → latest prompt → context → idle); the rest
(origin, bridge, model, cum tokens, opening prompt, window) drill down into an expand panel. Three
density presets (patrol / standard / debug), a settings drawer (reveal · theme · prompt line-clamp ·
ctx thresholds · columns · legend), and in-place rename (US6) writing back to ``POST /api/titles``.
Prompt summaries truncate by *visual line count* (CSS line-clamp) not character count, so CJK reads
as a first-class script. Per-row origin (cc-session-managed / rc-env-spawned / individual-cli, plus a
bridged marker) and the reconciliation strip (registry vs .url ledger vs the unreliable scrape, with
drift highlighted) are retained from the wide-table view — the drift is the tell.

This replaces the ``<meta refresh>`` server-rendered page (still available at ``/legacy`` for
curl / no-JS). Free-text (title/prompts) is redacted server-side in the payload when
``redact_default`` is on, so the client only ever displays what it is allowed to — there is no raw
text to leak here (reveal is a server behaviour switch, D3: single-user, no per-device auth). All
dynamic text is written via ``textContent`` / ``createElement`` (never ``innerHTML``), so a hostile
session name/prompt cannot inject markup.
"""
from __future__ import annotations

# Static document — no f-string (the JS/CSS use literal ``{}``). Served as a constant; the page
# carries no data, it subscribes to /api/stream for everything.
_PAGE = r"""<!doctype html><html lang=en><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<link rel=icon href="data:,">
<title>cc-monitor</title>
<style>
 /* --- design tokens (dark default; body.light swaps the palette) ------------------------------ */
 :root{
  --bg:#05070a; --panel:#0d1218; --row:#11171f; --card:#171d25; --well:rgba(0,0,0,.32);
  --t1:#f2f5f8; --t2:#c9d2da; --t3:#8b949e; --t4:#5f6a75;
  --bd:rgba(255,255,255,.14); --bd2:rgba(255,255,255,.09);
  --ok:#3fb950; --info:#4f9cf0; --warn:#d29922; --dgr:#f0564f;
  --okbg:rgba(63,185,80,.14); --infobg:rgba(79,156,240,.14); --warnbg:rgba(210,153,34,.15); --dgrbg:rgba(240,86,79,.14);
  --sh:0 1px 3px rgba(0,0,0,.5);
  --f-sans:'Noto Sans SC',system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
  --f-mono:'JetBrains Mono',ui-monospace,Menlo,Consolas,monospace;
  --pl:2;  /* prompt line-clamp; set from prefs */
  color-scheme:dark;
 }
 body.light{
  --bg:#eef0f2; --panel:#fff; --row:#fff; --card:#fff; --well:#f4f6f8;
  --t1:#1c2126; --t2:#38414b; --t3:#6b7480; --t4:#98a1ab;
  --bd:rgba(0,0,0,.13); --bd2:rgba(0,0,0,.08);
  --ok:#1f8a5b; --info:#2a6fdb; --warn:#b07508; --dgr:#cf3f38;
  --okbg:rgba(31,138,91,.12); --infobg:rgba(42,111,219,.1); --warnbg:rgba(176,117,8,.12); --dgrbg:rgba(207,63,56,.1);
  --sh:0 1px 2px rgba(0,0,0,.12);
  color-scheme:light;
 }
 *{box-sizing:border-box}
 body{background:var(--bg);color:var(--t2);font-family:var(--f-sans);margin:0;padding:0;font-size:14px}
 .mono{font-family:var(--f-mono)}
 .dim{color:var(--t4)}
 header{position:sticky;top:0;z-index:5;background:var(--panel);border-bottom:1px solid var(--bd2);
   padding:9px 14px;display:flex;align-items:center;gap:12px;flex-wrap:wrap}
 h1{font:600 15px var(--f-sans);color:var(--info);margin:0;letter-spacing:.2px}
 #meta{font:400 11px var(--f-mono);color:var(--t3);margin-left:6px}
 .grow{flex:1 1 auto}
 .badge{font:600 10.5px var(--f-mono);padding:2px 8px;border-radius:10px}
 #conn.up{background:var(--okbg);color:var(--ok)} #conn.down{background:var(--dgrbg);color:var(--dgr)}
 #reveal-badge{background:var(--warnbg);color:var(--warn)}
 .seg{display:inline-flex;border:1px solid var(--bd);border-radius:8px;overflow:hidden}
 .seg button{background:transparent;color:var(--t3);border:0;padding:5px 11px;font:500 12.5px var(--f-sans);cursor:pointer}
 .seg button.on{background:var(--infobg);color:var(--info)}
 .iconbtn{background:transparent;border:1px solid var(--bd);color:var(--t2);border-radius:7px;
   width:32px;height:30px;font-size:15px;cursor:pointer}
 #recon{display:flex;gap:7px;flex-wrap:wrap;align-items:center;padding:8px 14px;border-bottom:1px solid var(--bd2)}
 #recon .rlabel{font:500 11px var(--f-sans);color:var(--t3);cursor:pointer}
 .chip{font:500 11px var(--f-mono);padding:2px 8px;border-radius:5px;background:var(--well);color:var(--t2);cursor:help}
 .chip b{color:var(--t1)} .chip.drift{background:var(--warnbg);color:var(--warn)}
 .obadge{font:600 9.5px var(--f-mono);padding:1px 5px;border-radius:4px;background:var(--well);color:var(--t3);margin-left:6px;cursor:help}
 .bar{padding:8px 14px;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
 input,select{background:var(--row);color:var(--t2);border:1px solid var(--bd);border-radius:7px;
   padding:5px 9px;font:inherit;font-size:12.5px}
 #filter{min-width:min(260px,60vw);flex:1 1 auto}
 #count{font:400 11px var(--f-mono);color:var(--t3)}
 /* --- patrol stat cards --- */
 #cards{display:none;gap:10px;padding:2px 14px 8px;flex-wrap:wrap}
 #cards.show{display:flex}
 .stat{flex:1 1 150px;min-width:130px;background:var(--row);border:1px solid var(--bd2);border-radius:11px;
   padding:11px 13px;cursor:pointer;box-shadow:var(--sh)}
 .stat.on{border-color:var(--info);background:var(--infobg)}
 .stat .n{font:700 22px var(--f-mono);color:var(--t1)} .stat .k{font:500 11px var(--f-sans);color:var(--t3);margin-top:2px}
 /* --- main view --- */
 main{padding:6px 14px 24px}
 table{border-collapse:collapse;width:100%}
 th,td{text-align:left;padding:7px 10px;border-bottom:1px solid var(--bd2);vertical-align:top}
 th{font:600 10.5px var(--f-mono);color:var(--t3);text-transform:uppercase;letter-spacing:.4px;cursor:default}
 tr.srow{cursor:pointer} tr.srow:hover td{background:var(--row)}
 tr.busy td:first-child{box-shadow:inset 2px 0 0 var(--ok)}
 tr.orphaned td{background:var(--warnbg)} tr.orphaned td:first-child{box-shadow:inset 2px 0 0 var(--warn)}
 .st{font:500 12px var(--f-mono);white-space:nowrap}
 .dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px;vertical-align:middle}
 .dot.busy{background:var(--ok);animation:pulse 1.4s ease-in-out infinite}
 .dot.active{border:1.5px solid var(--info);background:transparent}
 .dot.orphaned{width:0;height:0;border-left:5px solid transparent;border-right:5px solid transparent;
   border-bottom:9px solid var(--warn);border-radius:0;margin-bottom:1px}
 @keyframes pulse{0%,100%{opacity:1}50%{opacity:.35}}
 .nm{font:500 13.5px var(--f-sans);color:var(--t1)} .nm.mono{font-family:var(--f-mono);font-size:12.5px}
 .redact{font-family:var(--f-mono);color:var(--t4);letter-spacing:1px}
 .clamp{display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:var(--pl);overflow:hidden;
   line-height:1.6;color:var(--t2);word-break:break-word}
 .ctxwrap{display:flex;align-items:center;gap:7px;white-space:nowrap}
 .barwrap{width:96px;height:8px;background:var(--well);border-radius:4px;overflow:hidden;flex:0 0 auto}
 .barfill{height:100%;border-radius:4px}
 .ctxlbl{font:500 11.5px var(--f-mono)}
 .idle{font:400 12px var(--f-mono);color:var(--t3);white-space:nowrap}
 /* --- expand detail (inline row + bottom sheet share .detail) --- */
 .detail{background:var(--well)}
 .dpad{padding:12px 14px;display:flex;flex-direction:column;gap:10px;border-left:2px solid var(--info)}
 .dbtns{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
 .btn{background:var(--row);border:1px solid var(--bd);color:var(--t2);border-radius:7px;
   padding:5px 11px;font:500 12px var(--f-sans);cursor:pointer}
 .btn.pri{background:var(--infobg);border-color:var(--info);color:var(--info)}
 .plabel{font:600 10.5px var(--f-mono);color:var(--t3);text-transform:uppercase;letter-spacing:.4px;margin-bottom:3px}
 .ptext{background:var(--row);border:1px solid var(--bd2);border-radius:8px;padding:9px 11px;
   line-height:1.75;white-space:pre-wrap;word-break:break-word;color:var(--t1)}
 .meta{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:7px}
 .mcell{background:var(--row);border:1px solid var(--bd2);border-radius:8px;padding:8px 11px;display:flex;gap:8px}
 .mcell .k{font:500 10.5px var(--f-sans);color:var(--t3);flex:0 0 66px}
 .mcell .v{font:400 12px var(--f-mono);color:var(--t2);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
 details summary{cursor:pointer;font:500 11.5px var(--f-sans);color:var(--t3)}
 /* --- cards / feed (mobile + debug) --- */
 .clist{display:flex;flex-direction:column;gap:9px}
 .scard{background:var(--card);border:1px solid var(--bd2);border-radius:11px;padding:11px 13px;box-shadow:var(--sh);cursor:pointer}
 .scard.orphaned{border-color:var(--warn)}
 .scard .top{display:flex;align-items:center;gap:8px;margin-bottom:6px}
 .feed .scard{cursor:default} .feed .ptext{max-width:760px}
 /* --- settings drawer + sheet backdrop --- */
 .backdrop{position:fixed;inset:0;background:rgba(0,0,0,.5);display:none;z-index:20}
 .backdrop.show{display:block}
 #settings{position:fixed;top:0;right:0;height:100%;width:min(380px,92vw);background:var(--panel);
   border-left:1px solid var(--bd);transform:translateX(100%);transition:transform .18s;z-index:21;
   overflow:auto;padding:16px}
 #settings.show{transform:none}
 .sgrp{border-top:1px solid var(--bd2);padding:12px 0}
 .sgrp h3{font:600 12px var(--f-sans);color:var(--t1);margin:0 0 8px}
 .srow{display:flex;align-items:center;justify-content:space-between;gap:10px;margin:6px 0;font-size:12.5px}
 .switch{cursor:pointer}
 .rangeval{font:600 12px var(--f-mono);color:var(--t1);min-width:34px;text-align:right}
 /* dual-handle range on one axis: two overlaid sliders + a tri-colour fill (ok / warn / danger) */
 .dual{position:relative;height:26px;margin:10px 2px 4px}
 .dual .dtrack{position:absolute;top:10px;left:0;right:0;height:6px;background:var(--ok);border-radius:3px}
 .dual .seg{position:absolute;top:10px;height:6px}
 .dual .dwarn{background:var(--warn)} .dual .ddgr{background:var(--dgr);border-radius:0 3px 3px 0}
 .dual input[type=range]{position:absolute;top:2px;left:0;width:100%;margin:0;height:22px;
   background:none;pointer-events:none;-webkit-appearance:none;appearance:none}
 .dual input[type=range]::-webkit-slider-runnable-track{background:transparent;height:22px}
 .dual input[type=range]::-moz-range-track{background:transparent;height:22px}
 .dual input[type=range]::-webkit-slider-thumb{-webkit-appearance:none;pointer-events:auto;
   width:16px;height:16px;border-radius:50%;background:var(--panel);border:2px solid var(--info);cursor:pointer;margin-top:0}
 .dual input[type=range]::-moz-range-thumb{pointer-events:auto;
   width:16px;height:16px;border-radius:50%;background:var(--panel);border:2px solid var(--info);cursor:pointer}
 #sheet{position:fixed;left:0;right:0;bottom:0;max-width:600px;margin:0 auto;background:var(--panel);
   border:1px solid var(--bd);border-bottom:0;border-radius:16px 16px 0 0;transform:translateY(100%);
   transition:transform .2s;z-index:22;max-height:86vh;overflow:auto}
 #sheet.show{transform:none}
 .sheeth{display:flex;justify-content:space-between;align-items:center;padding:11px 14px;border-bottom:1px solid var(--bd2)}
 /* --- mobile bottom density bar --- */
 #mdensity{position:fixed;left:0;right:0;bottom:0;background:var(--panel);border-top:1px solid var(--bd);
   display:none;z-index:15}
 #mdensity button{flex:1;min-height:46px;background:transparent;border:0;color:var(--t3);font:500 12.5px var(--f-sans);cursor:pointer}
 #mdensity button.on{color:var(--info)}
 .legend{font:400 11.5px var(--f-sans);color:var(--t3);line-height:1.7}
 .legend .dot{margin-right:8px}
 @media (max-width:719px){
  header{gap:8px} #density{display:none}
  #mdensity{display:flex} main{padding-bottom:64px}
 }
</style>

<header>
 <h1>cc-monitor</h1><span id=meta></span>
 <span class=grow></span>
 <span id=conn class="badge down">connecting…</span>
 <span id=reveal-badge class=badge hidden title="服务端已下发未脱敏原文（prompt / title）">原文</span>
 <div id=density class=seg role=group aria-label=density>
  <button data-d=patrol title="巡检：统计卡 + 精简列表，聚焦需关注">巡检</button>
  <button data-d=standard title="标准：桌面窄表格 / 手机卡片">标准</button>
  <button data-d=debug title="排查：单列 feed，prompt 全文无截断">排查</button>
 </div>
 <button id=gear class=iconbtn title="设置">&#9881;</button>
</header>

<div id=recon><span class=rlabel id=reconlabel title="来源核对：多个独立口径的会话计数；口径间的 drift（url-ledger vs managed、scraped vs registry）才是重点。点开图例。">来源核对 &#9432;</span></div>

<div class=bar>
 <input id=filter placeholder="过滤 名称 / prompt / model / uuid" aria-label=filter>
 <span id=count></span>
</div>

<div id=cards></div>
<main id=view></main>

<nav id=mdensity>
 <button data-d=patrol>巡检</button><button data-d=standard>标准</button><button data-d=debug>排查</button>
</nav>

<div class=backdrop id=sheet-bd></div>
<div id=sheet><div class=sheeth><b id=sheet-title class=nm>详情</b><button class=iconbtn id=sheet-x>&#10005;</button></div><div id=sheet-body></div></div>

<div class=backdrop id=set-bd></div>
<aside id=settings>
 <div class=srow><b class=nm>设置</b><button class=iconbtn id=set-x>&#10005;</button></div>
 <div class=sgrp><h3>隐私</h3>
  <div class=srow><label for=sw-reveal>显示原文 prompt / title</label><input type=checkbox id=sw-reveal class=switch></div>
  <div class=legend>关闭 = 服务端脱敏（显示 &#9619; 块）· 打开 = 服务端下发原文（header 常驻「原文」badge）。单用户，无设备认证。</div>
 </div>
 <div class=sgrp><h3>外观</h3>
  <div class=srow><label for=sw-theme>亮色主题</label><input type=checkbox id=sw-theme class=switch></div>
  <div class=srow><label for=in-lines>prompt 摘要行数</label>
   <span style="display:flex;align-items:center;gap:8px">
    <input type=range id=in-lines min=1 max=4 step=1 style=width:110px><b id=lines-val class=rangeval></b>
   </span></div>
 </div>
 <div class=sgrp><h3>context 阈值 (%)</h3>
  <div class=dual>
   <div class=dtrack></div><div class="seg dwarn" id=d-warn></div><div class="seg ddgr" id=d-dgr></div>
   <input type=range id=in-warn min=0 max=100 step=1 aria-label="关注阈值">
   <input type=range id=in-danger min=0 max=100 step=1 aria-label="危险阈值">
  </div>
  <div class=legend><span style=color:var(--warn)>关注</span> <b id=warnval class=mono></b>% 起 · <span style=color:var(--dgr)>危险</span> <b id=dangerval class=mono></b>% 起（拖动两个滑块）</div>
 </div>
 <div class=sgrp><h3>列（标准表格）</h3>
  <div class=srow><label for=col-prompt>最新 prompt</label><input type=checkbox id=col-prompt class=switch></div>
  <div class=srow><label for=col-ctx>context</label><input type=checkbox id=col-ctx class=switch></div>
  <div class=srow><label for=col-idle>idle</label><input type=checkbox id=col-idle class=switch></div>
 </div>
 <div class=sgrp><h3>图例</h3>
  <div class=legend>
   <div><span class="dot busy"></span>busy — 生成中，正在产出</div>
   <div><span class="dot active"></span>active — 已注册、可达，等待输入</div>
   <div><span class="dot orphaned"></span>orphaned — 台账残留，会话不可达（不可重命名）</div>
   <div style=margin-top:6px>context 着色：<span style=color:var(--ok)>正常</span> · <span style=color:var(--warn)>关注</span> · <span style=color:var(--dgr)>危险</span>（阈值可调）</div>
   <div style=margin-top:6px>origin：<b>mgd</b> cc-session-managed · <b>env</b> rc-env-spawned · <b>cli</b> individual-cli · <b>&middot;b</b> cloud-bridged</div>
   <div style=margin-top:6px>名称：override &gt; custom-title &gt; <span class=dim>— (cloud-side)</span>（未命名显示 uuid）</div>
   <div style=margin-top:6px>idle 由 last-activity 本地每秒推算（payload 无 wall-clock）。curl / 无 JS 用 <span class=mono>/legacy</span>。</div>
  </div>
 </div>
 <div class=sgrp><button class=btn id=set-reset>恢复默认</button></div>
</aside>

<script>
"use strict";
// ============================ prefs (localStorage, client-only, US4) ============================
const PKEY = "ccmon-proto-prefs";
const DEFAULTS = {density:"patrol", theme:"dark", promptLines:2, ctxWarn:50, ctxDanger:80,
  cols:{prompt:true, ctx:true, idle:true}};
function loadPrefs(){
  let p = {};
  try { p = JSON.parse(localStorage.getItem(PKEY) || "{}") || {}; } catch(_){ p = {}; }
  const m = Object.assign({}, DEFAULTS, p);
  m.cols = Object.assign({}, DEFAULTS.cols, p.cols || {});
  return m;
}
function savePrefs(){ try { localStorage.setItem(PKEY, JSON.stringify(prefs)); } catch(_){} }
let prefs = loadPrefs();

// reveal is a SERVER behaviour (redact_default) — not a localStorage pref. Mirrored from /api/config
// and flipped via POST /api/config so the un-redacted text is (or isn't) placed in the payload.
let revealOn = false;
const REDACT_MARK = "[redacted]";
const ORIGIN_ABBR = {"cc-session-managed":"mgd", "rc-env-spawned":"env", "individual-cli":"cli"};

// ============================ state ============================
let SESSIONS = [];
let patrolFilter = "attention";       // patrol stat-card selection: busy|active|attention|null
let openId = null;                    // session_id whose detail is expanded (inline or sheet)
const $ = (id) => document.getElementById(id);
const view = $("view");

// ============================ formatting ============================
function fmtK(n){ n = n||0; if (n >= 1e6) return (n/1e6).toFixed(1)+"M"; return n >= 1000 ? (n/1000).toFixed(1)+"k" : String(n); }
function shortModel(m){ return (m||"-").replace("claude-",""); }
function fmtIdle(s){ s = Math.max(0, Math.floor(s));
  if (s < 60) return s+"s";
  if (s < 3600){ const m = Math.floor(s/60); return m+"m"+(s%60)+"s"; }
  const h = Math.floor(s/3600); return h+"h"+Math.floor((s%3600)/60)+"m";
}
function nowS(){ return Date.now()/1000; }
function titleOf(r){                                  // override > custom-title > cloud-side
  if (r.override_title && r.override_title !== "") return {t:r.override_title, src:"override"};
  if (r.custom_title && r.custom_title !== "")     return {t:r.custom_title,   src:"custom"};
  return {t:"", src:"cloud-side"};
}
function isRedacted(v){ return v === REDACT_MARK; }
function ctxPct(r){ const w = r.win || 0; return w ? 100*(r.ctx||0)/w : 0; }
function ctxColor(pct){ return pct >= prefs.ctxDanger ? "var(--dgr)" : pct >= prefs.ctxWarn ? "var(--warn)" : "var(--ok)"; }
function needsAttention(r){ return r.status === "orphaned" || ctxPct(r) >= prefs.ctxWarn; }

// Write text safely; render the redaction marker as a masked block (never inject markup).
function putText(elm, s){
  elm.textContent = "";
  if (isRedacted(s)){ const b = document.createElement("span"); b.className = "redact"; b.textContent = "▓▓▓▓▓▓"; elm.appendChild(b); return; }
  elm.appendChild(document.createTextNode(s == null ? "" : String(s)));
}
function el(tag, cls, txt){ const e = document.createElement(tag); if (cls) e.className = cls; if (txt != null) e.textContent = txt; return e; }

// ============================ shared bits ============================
function statusDot(st){ return el("span", "dot " + st); }
function originBadge(r){
  if (!r.origin) return null;
  const b = el("span", "obadge", (ORIGIN_ABBR[r.origin] || "?") + (r.bridged ? "·b" : ""));
  b.title = r.origin + (r.bridged ? " · cloud-bridged" : "");
  return b;
}
function ctxCell(r){
  const wrap = el("span", "ctxwrap");
  const bw = el("span", "barwrap"), bf = el("span", "barfill");
  const pct = ctxPct(r), col = ctxColor(pct);
  bf.style.width = Math.min(pct, 100).toFixed(0)+"%"; bf.style.background = col;
  bw.appendChild(bf);
  const lbl = el("span", "ctxlbl");
  lbl.style.color = pct >= prefs.ctxWarn ? col : "var(--t2)";
  if (pct >= prefs.ctxDanger) lbl.style.fontWeight = "700";
  lbl.textContent = fmtK(r.ctx) + "/" + fmtK(r.win) + (r.win_certain ? "" : "?") + " (" + pct.toFixed(0) + "%)";
  wrap.appendChild(bw); wrap.appendChild(lbl);
  return wrap;
}
function displayName(r){
  const ti = titleOf(r);
  const span = el("span", "nm");
  if (ti.t){ putText(span, ti.t); }
  else if (r.name && r.name !== "-"){ span.className = "nm mono"; span.textContent = r.name; }
  else { span.className = "nm mono dim"; span.textContent = r.u8 || "—"; }
  return span;
}

// ============================ detail (inline + sheet) ============================
function buildDetail(r){
  const box = el("div", "dpad");
  const ti = titleOf(r);
  const btns = el("div", "dbtns");
  if (r.status !== "orphaned"){
    const rn = el("button", "btn pri", ti.src === "cloud-side" ? "命名" : "重命名");
    rn.onclick = (e) => { e.stopPropagation(); startRename(r, btns, ti); };
    btns.appendChild(rn);
  } else {
    btns.appendChild(el("span", "dim", "orphaned — 不可重命名"));
  }
  const ob = originBadge(r); if (ob) btns.appendChild(ob);
  box.appendChild(btns);
  box.appendChild(el("div", "plabel", "最新 prompt"));
  const lp = el("div", "ptext"); putText(lp, r.last_prompt || "—"); box.appendChild(lp);
  const det = el("details");
  det.appendChild(el("summary", null, "开场 prompt"));
  const ip = el("div", "ptext"); ip.style.marginTop = "6px"; putText(ip, r.initial_prompt || "—"); det.appendChild(ip);
  box.appendChild(det);
  const meta = el("div", "meta");
  const rows = [
    ["会话 ID", (r.u8 || "") + (r.session_id ? "  (" + r.session_id + ")" : "")],
    ["origin", (r.origin || "—") + (r.bridged ? " · bridged" : "")],
    ["bridge", r.bridge_id || "—"],
    ["model", shortModel(r.model)],
    ["s-effort", r.session_effort || "—"],
    ["累计 tok", "↓" + fmtK(r.cum_input) + " ↑" + fmtK(r.cum_output)],
    ["窗口", fmtK(r.win) + (r.win_certain ? "" : " (?)")],
    ["状态", r.status],
  ];
  rows.forEach(function(kv){
    const c = el("div", "mcell"); c.appendChild(el("span", "k", kv[0]));
    const vv = el("span", "v"); vv.textContent = kv[1]; vv.title = String(kv[1]); c.appendChild(vv); meta.appendChild(c);
  });
  box.appendChild(meta);
  return box;
}
function startRename(r, mount, ti){
  mount.textContent = "";
  const inp = el("input"); inp.value = ti.t || ""; inp.placeholder = "Enter 保存 / 空值清除"; inp.style.minWidth = "220px";
  const key = r.session_id || r.bridge_id;
  const commit = () => { postTitle(key, inp.value.trim()); };  // SSE update reflows the row
  inp.onkeydown = (e) => {
    e.stopPropagation();
    if (e.key === "Enter"){ commit(); }
    else if (e.key === "Escape"){ reopenDetail(r); }
  };
  const ok = el("button", "btn pri", "保存"); ok.onclick = (e) => { e.stopPropagation(); commit(); };
  mount.appendChild(inp); mount.appendChild(ok); inp.focus();
}
function reopenDetail(r){
  if ($("sheet").classList.contains("show")) openSheet(r); else renderView();
}

// ============================ patrol / table / cards / feed ============================
function filtered(){
  const q = $("filter").value.trim().toLowerCase();
  return SESSIONS.filter(r => {
    if (!q) return true;
    const hay = [r.name, r.custom_title, r.override_title, r.initial_prompt, r.last_prompt, r.model, r.u8, r.origin];
    return hay.some(v => (v||"").toLowerCase().includes(q));
  });
}
function renderView(){
  const d = prefs.density;
  $("cards").className = d === "patrol" ? "show" : "";
  view.textContent = "";
  let rows = filtered();
  if (d === "patrol"){ paintStatCards(rows); rows = rows.filter(patrolPass); }
  rows = rows.slice().sort((a,b) =>
    (a.status!=="busy") - (b.status!=="busy") || (b.last_activity_ts||0) - (a.last_activity_ts||0));
  $("count").textContent = rows.length + " 显示 / " + SESSIONS.length + " 会话";
  const mobile = window.innerWidth < 720;
  if (d === "debug") renderFeed(rows);
  else if (d === "standard" && !mobile) renderTable(rows);
  else renderCards(rows);
}
function patrolPass(r){
  if (patrolFilter === "busy") return r.status === "busy";
  if (patrolFilter === "active") return r.status === "active";
  if (patrolFilter === "attention") return needsAttention(r);
  return true;
}
function paintStatCards(rows){
  const c = $("cards"); c.textContent = "";
  const defs = [["busy","生成中",rows.filter(r=>r.status==="busy").length],
                ["active","可达待命",rows.filter(r=>r.status==="active").length],
                ["attention","需关注",rows.filter(needsAttention).length]];
  defs.forEach(function(dd){
    const card = el("div", "stat" + (patrolFilter===dd[0]?" on":""));
    card.appendChild(el("div", "n", String(dd[2])));
    card.appendChild(el("div", "k", dd[1]));
    card.onclick = () => { patrolFilter = patrolFilter===dd[0] ? null : dd[0]; renderView(); };
    c.appendChild(card);
  });
}
function renderTable(rows){
  const cols = prefs.cols;
  const table = el("table"), thead = el("thead"), htr = el("tr");
  const heads = ["status","名称"];
  if (cols.prompt) heads.push("最新 prompt");
  if (cols.ctx) heads.push("context");
  if (cols.idle) heads.push("idle");
  heads.forEach(h => htr.appendChild(el("th", null, h)));
  thead.appendChild(htr); table.appendChild(thead);
  const tb = el("tbody");
  rows.forEach(r => {
    const tr = el("tr", "srow " + r.status);
    const stc = el("td"); const st = el("span", "st"); st.appendChild(statusDot(r.status));
    st.appendChild(document.createTextNode(r.status)); stc.appendChild(st); tr.appendChild(stc);
    const nmc = el("td"); nmc.appendChild(displayName(r)); const ob = originBadge(r); if (ob) nmc.appendChild(ob); tr.appendChild(nmc);
    if (cols.prompt){ const pc = el("td"); const cl = el("div", "clamp"); putText(cl, r.last_prompt || "—"); pc.appendChild(cl); tr.appendChild(pc); }
    if (cols.ctx){ const cc = el("td"); cc.appendChild(ctxCell(r)); tr.appendChild(cc); }
    if (cols.idle){ const ic = el("td"); const id = el("span", "idle"); id.dataset.ts = r.last_activity_ts||0; tickEl(id); ic.appendChild(id); tr.appendChild(ic); }
    tr.onclick = () => { openId = (openId === r.session_id) ? null : r.session_id; renderView(); };
    tb.appendChild(tr);
    if (r.session_id === openId){ tb.appendChild(inlineDetailRow(r, heads.length)); }
  });
  table.appendChild(tb); view.appendChild(table);
}
function inlineDetailRow(r, span){
  const tr = el("tr"); tr.dataset.detail = r.session_id;
  const td = el("td", "detail"); td.colSpan = span; td.appendChild(buildDetail(r)); tr.appendChild(td); return tr;
}
function renderCards(rows){
  const list = el("div", "clist");
  rows.forEach(r => {
    const card = el("div", "scard " + (r.status==="orphaned"?"orphaned":""));
    const top = el("div", "top"); top.appendChild(statusDot(r.status)); top.appendChild(displayName(r));
    const ob = originBadge(r); if (ob) top.appendChild(ob);
    top.appendChild(el("span", "grow"));
    card.appendChild(top);
    const cl = el("div", "clamp"); putText(cl, r.last_prompt || "—"); card.appendChild(cl);
    const foot = el("div"); foot.style.cssText = "display:flex;gap:10px;align-items:center;margin-top:7px";
    foot.appendChild(ctxCell(r));
    const id = el("span", "idle"); id.dataset.ts = r.last_activity_ts||0; tickEl(id); foot.appendChild(id);
    card.appendChild(foot);
    card.onclick = () => openSheet(r);
    list.appendChild(card);
  });
  view.appendChild(list);
}
function renderFeed(rows){
  const list = el("div", "clist feed");
  rows.forEach(r => {
    const card = el("div", "scard " + (r.status==="orphaned"?"orphaned":""));
    const top = el("div", "top"); top.appendChild(statusDot(r.status)); top.appendChild(displayName(r));
    const ob = originBadge(r); if (ob) top.appendChild(ob);
    top.appendChild(el("span", "grow"));
    const rn = el("button", "btn", "详情");
    rn.onclick = (e) => { e.stopPropagation(); openSheet(r); }; top.appendChild(rn);
    card.appendChild(top);
    card.appendChild(el("div", "plabel", "最新 prompt")); const lp = el("div", "ptext"); putText(lp, r.last_prompt || "—"); card.appendChild(lp);
    const foot = el("div"); foot.style.cssText = "display:flex;gap:10px;align-items:center;margin-top:8px";
    foot.appendChild(ctxCell(r));
    const id = el("span", "idle"); id.dataset.ts = r.last_activity_ts||0; tickEl(id); foot.appendChild(id);
    card.appendChild(foot);
    list.appendChild(card);
  });
  view.appendChild(list);
}

// ============================ bottom sheet ============================
function openSheet(r){
  openId = r.session_id;
  putText($("sheet-title"), titleOf(r).t || r.name || r.u8 || "详情");
  const body = $("sheet-body"); body.textContent = ""; body.appendChild(buildDetail(r));
  $("sheet").classList.add("show"); $("sheet-bd").classList.add("show");
}
function closeSheet(){ openId = null; $("sheet").classList.remove("show"); $("sheet-bd").classList.remove("show"); }

// ============================ recon / reconciliation strip ============================
function paintRecon(rc){
  const strip = $("recon"); strip.textContent = "";
  strip.appendChild(mkReconLabel());
  if (!rc || rc.registry === undefined) return;
  const scr = rc.scraped;
  const items = [
    ["registry", rc.registry, false, "本地 registry 会话数（真值口径）"],
    ["managed", rc.managed, false, "cc-session-managed"],
    ["env-spawned", rc.rc_env_spawned, false, "rc-env-spawned（sdk-cli）"],
    ["individual", rc.individual_cli, false, "individual-cli"],
    ["bridged", rc.bridged, false, "cloud-bridged"],
    ["url-ledger", rc.url_ledger, rc.url_ledger !== rc.managed, "supervisor .url 台账（可能含残留 > managed）"],
    ["scraped", scr == null ? "—" : scr, scr != null && String(scr) !== String(rc.registry), "cc-session tmux 抓取（不可靠；vs registry 的 drift 是信号）"],
  ];
  items.forEach(function(it){ strip.appendChild(chip(it[0] + " ", it[1], it[3], it[2])); });
}
function mkReconLabel(){
  const s = el("span", "rlabel", "来源核对 ␲");
  s.title = "来源核对：多口径会话计数；drift（url-ledger vs managed、scraped vs registry）是重点。点开图例。";
  s.onclick = openSettings; return s;
}
function chip(k, v, tip, drift){
  const c = el("span", "chip" + (drift ? " drift" : "")); c.title = tip || "";
  if (k) c.appendChild(document.createTextNode(k));
  c.appendChild(el("b", null, String(v))); return c;
}

// ============================ header ============================
function paintHeader(d){
  const parts = ["effort " + (d && d.effort ? d.effort : "?"), SESSIONS.length + " 会话"];
  if (d && d.cc_session){
    const p = d.prom || {};
    parts.push("RC " + (p.rc_connected === "1" ? "connected" : "DOWN/?"));
  } else if (d && d.cc_session === false){ parts.push("standalone"); }
  $("meta").textContent = parts.join(" · ");
  $("reveal-badge").hidden = !revealOn;
}

// ============================ transport ============================
let LAST = {};
function apply(d){ LAST = d; SESSIONS = d.sessions || []; paintHeader(d); paintRecon(d.recon); renderView(); refreshOpenSheet(); }
function refreshOpenSheet(){
  if (openId && $("sheet").classList.contains("show")){
    const r = SESSIONS.find(s => s.session_id === openId);
    if (r){ const body = $("sheet-body"); body.textContent = ""; body.appendChild(buildDetail(r)); }
  }
}
function setConn(up){ const e = $("conn"); e.textContent = up ? "实时" : "重连中…"; e.className = "badge " + (up ? "up" : "down"); }
function connect(){
  const es = new EventSource("/api/stream");
  es.onopen = () => setConn(true);
  es.onmessage = (e) => { setConn(true); try { apply(JSON.parse(e.data)); } catch(_){} };
  es.onerror = () => setConn(false);              // EventSource auto-reconnects; just reflect state
}

// ============================ config (reveal + threshold defaults) ============================
function loadConfig(){
  fetch("/api/config").then(r => r.json()).then(c => {
    revealOn = c.redact_default === false;        // reveal = server NOT redacting
    let sp = {}; try { sp = JSON.parse(localStorage.getItem(PKEY) || "{}") || {}; } catch(_){}
    if (typeof c.ctx_warn_pct === "number" && sp.ctxWarn == null) prefs.ctxWarn = c.ctx_warn_pct;
    if (typeof c.ctx_crit_pct === "number" && sp.ctxDanger == null) prefs.ctxDanger = c.ctx_crit_pct;
    syncSettingsUI(); paintHeader(LAST); renderView();
  }).catch(() => {});
}
function postConfig(patch){
  fetch("/api/config", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(patch)})
    .then(r => r.json()).then(c => { revealOn = c.redact_default === false; paintHeader(LAST); }).catch(()=>{});
}
function postTitle(key, title){
  fetch("/api/titles", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({key:key, title:title})}).catch(()=>{});
}

// ============================ settings drawer ============================
function openSettings(){ syncSettingsUI(); $("settings").classList.add("show"); $("set-bd").classList.add("show"); }
function closeSettings(){ $("settings").classList.remove("show"); $("set-bd").classList.remove("show"); }
function syncSettingsUI(){
  $("sw-reveal").checked = revealOn;
  $("sw-theme").checked = prefs.theme === "light";
  $("in-lines").value = prefs.promptLines;
  $("col-prompt").checked = prefs.cols.prompt;
  $("col-ctx").checked = prefs.cols.ctx;
  $("col-idle").checked = prefs.cols.idle;
  applyLines(); paintDual();
}
function applyTheme(){ document.body.classList.toggle("light", prefs.theme === "light"); }
function applyLines(){
  document.documentElement.style.setProperty("--pl", prefs.promptLines);
  $("lines-val").textContent = prefs.promptLines + " 行";
}
// dual-handle ctx threshold slider: warn <= danger; tri-colour fill (ok 0..warn / warn..danger / danger..100)
function paintDual(){
  const w = prefs.ctxWarn, dg = prefs.ctxDanger;
  $("in-warn").value = w; $("in-danger").value = dg;
  $("warnval").textContent = w; $("dangerval").textContent = dg;
  $("d-warn").style.left = w + "%"; $("d-warn").style.width = Math.max(0, dg - w) + "%";
  $("d-dgr").style.left = dg + "%"; $("d-dgr").style.width = Math.max(0, 100 - dg) + "%";
}

// ============================ idle local tick ============================
function tickEl(elm){ const ts = +elm.dataset.ts || 0; elm.textContent = ts ? fmtIdle(nowS() - ts) : "—"; }
function tickAll(){ view.querySelectorAll(".idle").forEach(tickEl); }

// ============================ wire up ============================
function setDensity(d){
  prefs.density = d; savePrefs();
  document.querySelectorAll("#density button, #mdensity button").forEach(b => b.classList.toggle("on", b.dataset.d === d));
  closeSheet(); renderView();
}
document.querySelectorAll("#density button, #mdensity button").forEach(b => b.onclick = () => setDensity(b.dataset.d));
$("filter").addEventListener("input", renderView);
$("gear").onclick = openSettings;
$("set-x").onclick = closeSettings; $("set-bd").onclick = closeSettings;
$("sheet-x").onclick = closeSheet; $("sheet-bd").onclick = closeSheet;
$("sw-reveal").onchange = (e) => { revealOn = e.target.checked; postConfig({redact_default: !revealOn}); };
$("sw-theme").onchange = (e) => { prefs.theme = e.target.checked ? "light" : "dark"; savePrefs(); applyTheme(); };
$("in-lines").oninput = (e) => { prefs.promptLines = +e.target.value; savePrefs(); applyLines(); renderView(); };
$("in-warn").oninput = (e) => {                                   // warn can't pass danger
  prefs.ctxWarn = Math.min(Math.max(0, +e.target.value||0), prefs.ctxDanger);
  savePrefs(); paintDual(); renderView(); };
$("in-danger").oninput = (e) => {                                 // danger can't drop below warn
  prefs.ctxDanger = Math.max(Math.min(100, +e.target.value||0), prefs.ctxWarn);
  savePrefs(); paintDual(); renderView(); };
["prompt","ctx","idle"].forEach(k => $("col-"+k).onchange = (e) => { prefs.cols[k] = e.target.checked; savePrefs(); renderView(); });
$("set-reset").onclick = () => { prefs = Object.assign({}, DEFAULTS); prefs.cols = Object.assign({}, DEFAULTS.cols); savePrefs(); applyTheme(); applyLines(); syncSettingsUI(); renderView(); };
window.addEventListener("resize", renderView);
document.addEventListener("keydown", (e) => { if (e.key === "Escape"){ closeSheet(); closeSettings(); } });

// init
applyTheme(); applyLines(); setDensity(prefs.density); syncSettingsUI();
loadConfig(); connect();
setInterval(tickAll, 1000);
</script>
</html>
"""

_PAGE_BYTES = _PAGE.encode("utf-8")


def spa_page() -> bytes:
    """The static SPA document (constant bytes). Data arrives over ``/api/stream``."""
    return _PAGE_BYTES
