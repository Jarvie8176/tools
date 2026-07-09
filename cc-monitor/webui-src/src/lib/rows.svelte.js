// session payload → 行视图模型（在组件 $derived 中调用，追踪 feed/prefs/ui 响应）。
// 映射真实 SSE payload 字段（stream.serialize）→ 设计稿的行模型。脱敏由服务端完成：被脱敏的
// 自由文本以 "[redacted]" 到达，客户端渲染为 ▓ 块（不再客户端 mask）。
import { feed } from './data.svelte.js';
import { prefs, ui, eff } from './state.svelte.js';
import { fmtIdle, fmtK } from './fmt.js';

const REDACT = '[redacted]';
const BLOCK = '▓▓▓▓▓▓▓▓▓▓';
const ORIGIN_LABEL = {
  'cc-session-managed': 'managed', 'rc-env-spawned': 'env-spawned', 'individual-cli': 'individual-cli'
};
const shortModel = (m) => (m || '—').replace('claude-', '');
// server-redacted free text arrives as the marker → render a masked block; else the text itself
const disp = (t) => (t === REDACT ? BLOCK : t);

export function buildRows() {
  return feed.sessions.map((s) => {
    const orphan = s.status === 'orphaned';
    const busy = s.status === 'busy';
    const rawTitle = s.override_title || s.custom_title || '';
    const named = !!rawTitle;
    const redactedTitle = rawTitle === REDACT;
    const win = s.win || 0;
    const pct = win ? Math.round((s.ctx / win) * 100) : 0;
    const level = orphan ? 'off' : pct >= eff.danger ? 'dgr' : pct >= eff.warn ? 'warn' : 'ok';
    const idleMs = s.last_activity_ts ? Math.max(0, ui.now - s.last_activity_ts * 1000) : 0;
    const origin = (ORIGIN_LABEL[s.origin] || s.origin || '—') + (s.bridged ? ' · bridged' : '');
    const sub = orphan ? '.url 台账残留'
      : named ? `${s.u8} · 手动命名`
      : s.bridged ? '未命名 · cloud-side' : '未命名';

    return {
      id: s.session_id,
      status: s.status, orphan, busy, named,
      rawName: named ? disp(rawTitle) : '',
      dispName: named ? (redactedTitle ? BLOCK : rawTitle) : (s.u8 || s.session_id),
      mono: !named || redactedTitle,
      sub,
      prompt: orphan
        ? '不可达 — .url 引用无对应 live session（registry 无条目）'
        : disp(s.last_prompt) || '—',
      pInit: orphan ? null : (disp(s.initial_prompt) || '—'),
      pct, level,
      ctxLabel: orphan ? '—' : fmtK(s.ctx) + ' / ' + fmtK(win),
      idleStr: fmtIdle(idleMs),
      attn: orphan || pct >= eff.warn,
      attnLevel: orphan ? 'warn' : pct >= eff.danger ? 'dgr' : 'warn',
      attnReason: orphan
        ? '不可达 · .url 残留'
        : pct >= eff.danger ? `context ${pct}% · 接近上限` : `context ${pct}% · 偏高`,
      uuid: (s.u8 || '') + '…',
      fullId: s.session_id || s.bridge_id || '',
      bridge: s.bridge_id ? s.bridge_id + '…' : '—',
      model: orphan ? '—' : shortModel(s.model),
      effort: s.session_effort || null,
      modelStr: orphan ? '—' : (s.session_effort ? `${shortModel(s.model)} · 推理 ${s.session_effort}` : shortModel(s.model)),
      cum: orphan ? '—' : (s.full ? `↓${fmtK(s.cum_input)} ↑${fmtK(s.cum_output)}` : '(大会话)'),
      winStr: fmtK(win) + (s.win_certain ? ' 实测' : ' ?'),
      origin,
      expanded: ui.expanded === s.session_id,
      renaming: ui.renaming === s.session_id
    };
  });
}
