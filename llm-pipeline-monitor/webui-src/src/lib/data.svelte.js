// Live feed: the SSE /api/stream payload as reactive state, plus the runtime config knobs
// (/api/config). The payload carries only numeric endpoint metrics + a served model path — no
// free-text user content — so there is nothing to redact client-side.

export const feed = $state({
  rows: [], ok: false, error: null, connected: false
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

// Debounced persist: a slider drag fires oninput per pixel. Update the UI optimistically at once,
// but collapse the POST storm into a single trailing write — otherwise many concurrent POSTs return
// out of order and a stale reply bounces the thumb backward.
let _pending = {};
let _timer = null;

export function saveCfg(partial) {
  Object.assign(cfg, partial);      // optimistic — immediate, responsive
  Object.assign(_pending, partial); // accumulate for the trailing flush
  clearTimeout(_timer);
  _timer = setTimeout(_flush, 250);
}

async function _flush() {
  const body = _pending;
  _pending = {};
  try {
    const r = await fetch('/api/config', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
    const server = await r.json();
    // reconcile with server-clamped values, but never clobber a key the user is still editing
    // (accumulated into _pending while this request was in flight).
    for (const [k, v] of Object.entries(server)) {
      if (!(k in _pending)) cfg[k] = v;
    }
  } catch { /* leave optimistic value */ }
}
