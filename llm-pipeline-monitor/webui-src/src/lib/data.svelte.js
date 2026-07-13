// Live feed: the SSE /api/stream payload as reactive state, plus the runtime config knobs
// (/api/config). The payload carries only numeric endpoint metrics + a served model path — no
// free-text user content — so there is nothing to redact client-side.

export const feed = $state({
  rows: [], ok: false, error: null, prom_url: '', connected: false
});

export function connectFeed() {
  const es = new EventSource('/api/stream');
  es.onopen = () => (feed.connected = true);
  es.onmessage = (e) => {
    feed.connected = true;
    try {
      const d = JSON.parse(e.data);
      feed.rows = d.rows || [];
      feed.ok = !!d.ok;
      feed.error = d.error ?? null;
      feed.prom_url = d.prom_url || '';
    } catch { /* ignore malformed frame */ }
  };
  es.onerror = () => (feed.connected = false); // EventSource auto-reconnects
  return es;
}

// Runtime config (thresholds). Loaded once, persisted server-side via POST /api/config.
export const cfg = $state({
  ctx_warn_pct: 50, ctx_crit_pct: 80, vram_warn_pct: 85, tps_floor: 15
});

export async function loadCfg() {
  try {
    const r = await fetch('/api/config');
    Object.assign(cfg, await r.json());
  } catch { /* keep defaults */ }
}

export async function saveCfg(partial) {
  Object.assign(cfg, partial); // optimistic
  try {
    const r = await fetch('/api/config', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(partial)
    });
    Object.assign(cfg, await r.json()); // reconcile with server-clamped values
  } catch { /* leave optimistic value */ }
}
