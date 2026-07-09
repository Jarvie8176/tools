// 全局状态（Svelte 5 runes）：偏好 = localStorage 仅本机（US4）；瞬态 UI 不持久化。
// reveal 是服务端行为开关（redact_default）——即时 POST /api/config，不进 save/discard 快照。
import { connectFeed } from './data.svelte.js';

const KEY = 'ccmon-prefs';

const DEFAULT_PREFS = {
  density: 'standard',       // 'patrol' | 'standard' | 'debug'
  reveal: false,             // US5：镜像服务端 redact_default（false = 服务端脱敏下发）
  theme: 'dark',
  colsOverride: null,        // {prompt,ctx,idle} | null（null = 跟随预设）
  promptLines: null,         // 1–4 | null（null = 默认 2）
  ctxWarn: null,             // 10–90 | null（默认 50）
  ctxDanger: null,           // 20–95 | null（默认 75）
  webFonts: true,            // 加载设计 Web 字体（Noto Sans SC / JetBrains Mono）；关 = 系统字体离线
  titles: {}                 // 兼容占位；写回走 POST /api/titles，SSE 回流刷新（US6）
};

function load() {
  try {
    return { ...structuredClone(DEFAULT_PREFS), ...(JSON.parse(localStorage.getItem(KEY) || '{}') || {}) };
  } catch {
    return structuredClone(DEFAULT_PREFS);
  }
}

export const prefs = $state(load());

export const ui = $state({
  expanded: null, renaming: null, renameVal: '', initOpen: false,
  settingsOpen: false, confirmClose: false,
  patrolFilter: 'attn', reconOpen: false,
  isMobile: false, now: Date.now()
});

export function persist() {
  try { localStorage.setItem(KEY, JSON.stringify($state.snapshot(prefs))); } catch {}
}

/* ── 生效值（阈值/行数可在设置中调）── */
export const eff = {
  get warn() { return prefs.ctxWarn ?? 50; },
  get danger() { return prefs.ctxDanger ?? 75; },
  get lines() { return prefs.promptLines ?? 2; },
  get cols() {
    if (prefs.colsOverride) return prefs.colsOverride;
    return prefs.density === 'patrol'
      ? { prompt: false, ctx: true, model: true, idle: true }
      : { prompt: true, ctx: true, model: true, idle: true };
  }
};

/* ── 后端接线（真实数据）── */
function postJSON(url, body) {
  return fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
}
export function postTitle(id, title) { postJSON('/api/titles', { key: id, title }).catch(() => {}); }
export function setReveal(on) {
  prefs.reveal = on;                                   // optimistic; server confirms via next payload
  postJSON('/api/config', { redact_default: !on }).catch(() => {});
}
export async function loadConfig() {
  try { const c = await (await fetch('/api/config')).json(); prefs.reveal = c.redact_default === false; } catch {}
}
export function init() { loadConfig(); return connectFeed(); }

/* ── 密度（切换预设重置列自定义，立即持久化）── */
export function setDensity(d) {
  prefs.density = d;
  prefs.colsOverride = null;
  ui.expanded = null;
  persist();
}

/* ── 行展开 ── */
export function toggleExpand(id) {
  ui.expanded = ui.expanded === id ? null : id;
  ui.renaming = null;
  ui.initOpen = false;
}
export function closeSheet() {
  ui.expanded = null;
  ui.renaming = null;
  ui.initOpen = false;
}

/* ── 重命名（US6）：服务端写回，SSE 回流刷新 ── */
export function startRename(id, current) {
  ui.expanded = id;
  ui.renaming = id;
  ui.renameVal = current || '';
}
export function commitRename() {
  if (!ui.renaming) return;
  const id = ui.renaming;
  const v = (ui.renameVal || '').trim();
  postTitle(id, v);              // 空值 = 清除 override；服务端原子写，下一次 collect 经 SSE 反映
  ui.renaming = null;
}
export function cancelRename() { ui.renaming = null; }

/* ── 设置：改动即时预览，「保存」才落盘；关闭前未保存提示（reveal 除外——即时服务端）── */
const SETTING_KEYS = ['theme', 'colsOverride', 'promptLines', 'ctxWarn', 'ctxDanger', 'webFonts'];
let snapshot = $state(null);
const pick = () => JSON.stringify(SETTING_KEYS.map((k) => prefs[k]));

export function settingsDirty() { return snapshot !== null && pick() !== snapshot; }
export function openSettings() { snapshot = pick(); ui.settingsOpen = true; ui.confirmClose = false; }
export function closeSettings() {
  if (settingsDirty()) ui.confirmClose = true;
  else { ui.settingsOpen = false; ui.confirmClose = false; snapshot = null; }
}
export function saveSettings() { snapshot = null; persist(); ui.settingsOpen = false; ui.confirmClose = false; }
export function discardSettings() {
  const s = JSON.parse(snapshot);
  SETTING_KEYS.forEach((k, i) => { prefs[k] = s[i]; });
  snapshot = null; ui.settingsOpen = false; ui.confirmClose = false;
}
export function keepEditing() { ui.confirmClose = false; }
export function resetSettings() {
  prefs.theme = 'dark'; prefs.colsOverride = null;
  prefs.promptLines = null; prefs.ctxWarn = null; prefs.ctxDanger = null; prefs.webFonts = true;
}
export function toggleCol(k) {
  const c = { ...eff.cols };
  c[k] = !c[k];
  prefs.colsOverride = c;
}
