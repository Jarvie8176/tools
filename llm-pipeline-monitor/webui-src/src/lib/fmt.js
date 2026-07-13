export function fmtIdle(ms) {
  const s = Math.max(0, Math.floor(ms / 1000));
  if (s < 60) return s + 's';
  const m = Math.floor(s / 60);
  if (m < 60) return m + 'm' + (s % 60) + 's';
  return Math.floor(m / 60) + 'h' + (m % 60) + 'm';
}

export function fmtK(n) {
  return n >= 1e6 ? (n / 1e6).toFixed(1) + 'M' : (n / 1000).toFixed(1) + 'k';
}

// 服务端脱敏的客户端表现（原型模拟；实现侧由 payload redacted 字段决定）
export function mask(t) {
  return '▓'.repeat(Math.max(8, Math.min(30, Math.round((t || '').length / 5))));
}

// ctx 等级 → 语义色 class
export const CTX_TEXT = { ok: 'text-ok', warn: 'text-warn', dgr: 'text-dgr', off: 'text-t4' };
export const CTX_BG = { ok: 'bg-ok', warn: 'bg-warn', dgr: 'bg-dgr', off: 'bg-t4' };
