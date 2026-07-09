import type { Payload, Prefs, Session, Density } from "./types";
import { ctxPct } from "./format";

const PKEY = "ccmon-proto-prefs";
const DEFAULT_PREFS: Prefs = {
  density: "patrol", theme: "dark", promptLines: 2, ctxWarn: 50, ctxDanger: 80,
  cols: { prompt: true, ctx: true, idle: true },
};

function loadPrefs(): Prefs {
  try {
    const p = JSON.parse(localStorage.getItem(PKEY) || "{}") || {};
    return { ...DEFAULT_PREFS, ...p, cols: { ...DEFAULT_PREFS.cols, ...(p.cols || {}) } };
  } catch { return { ...DEFAULT_PREFS, cols: { ...DEFAULT_PREFS.cols } }; }
}

// Reactive app state (Svelte 5 runes). One module-level singleton; components import `store`.
class Store {
  payload = $state<Payload>({ sessions: [], prom: {}, cc_session: false, effort: null,
    recon: { registry: 0, managed: 0, rc_env_spawned: 0, individual_cli: 0, bridged: 0, url_ledger: 0, scraped: null } });
  prefs = $state<Prefs>(loadPrefs());
  revealOn = $state(false);          // server redact_default === false
  connected = $state(false);
  filter = $state("");
  patrolFilter = $state<"busy" | "active" | "attention" | null>("attention");
  openId = $state<string | null>(null);
  tick = $state(0);                  // bumped every 1s so idle durations re-derive

  sessions = $derived(this.payload.sessions);

  savePrefs() { try { localStorage.setItem(PKEY, JSON.stringify(this.prefs)); } catch { /* ignore */ } }
  setDensity(d: Density) { this.prefs.density = d; this.openId = null; this.savePrefs(); }
  needsAttention(r: Session) { return r.status === "orphaned" || ctxPct(r) >= this.prefs.ctxWarn; }

  connect() {
    const es = new EventSource("/api/stream");
    es.onopen = () => (this.connected = true);
    es.onmessage = (e) => { this.connected = true; try { this.payload = JSON.parse(e.data); } catch { /* ignore */ } };
    es.onerror = () => (this.connected = false);
  }
  async loadConfig() {
    try {
      const c = await (await fetch("/api/config")).json();
      this.revealOn = c.redact_default === false;
      let sp: any = {};
      try { sp = JSON.parse(localStorage.getItem(PKEY) || "{}") || {}; } catch { /* ignore */ }
      if (typeof c.ctx_warn_pct === "number" && sp.ctxWarn == null) this.prefs.ctxWarn = c.ctx_warn_pct;
      if (typeof c.ctx_crit_pct === "number" && sp.ctxDanger == null) this.prefs.ctxDanger = c.ctx_crit_pct;
    } catch { /* offline: keep defaults */ }
  }
  async setReveal(on: boolean) {
    this.revealOn = on;
    try {
      const c = await (await fetch("/api/config", { method: "POST",
        headers: { "Content-Type": "application/json" }, body: JSON.stringify({ redact_default: !on }) })).json();
      this.revealOn = c.redact_default === false;
    } catch { /* ignore */ }
  }
  async rename(key: string, title: string) {
    try {
      await fetch("/api/titles", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key, title }) });
    } catch { /* ignore; SSE will reflect on success */ }
  }
}

export const store = new Store();
