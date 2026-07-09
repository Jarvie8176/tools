// Live feed: the SSE /api/stream payload as reactive state. Replaces the design pack's mock
// SESSIONS/RECON (see README §接入真实数据). Redaction is server-side — the client only renders
// what the payload carries ("[redacted]" for masked free text); reveal flips the server behaviour.
export const feed = $state({
  sessions: [], recon: null, prom: {}, cc_session: false, effort: null, connected: false
});

export function connectFeed() {
  const es = new EventSource('/api/stream');
  es.onopen = () => (feed.connected = true);
  es.onmessage = (e) => {
    feed.connected = true;
    try {
      const d = JSON.parse(e.data);
      feed.sessions = d.sessions || [];
      feed.recon = d.recon || null;
      feed.prom = d.prom || {};
      feed.cc_session = !!d.cc_session;
      feed.effort = d.effort ?? null;
    } catch { /* ignore malformed frame */ }
  };
  es.onerror = () => (feed.connected = false); // EventSource auto-reconnects
  return es;
}

export const RECON_LEGEND = [
  { term: 'registry', warn: false, desc: '服务端注册的 live session — 可达会话的权威来源' },
  { term: 'managed', warn: false, desc: '本机 supervisor 托管启动' },
  { term: 'env-spawned', warn: false, desc: '云端环境派生，经 bridge 上报' },
  { term: 'individual', warn: false, desc: '独立 CLI（非 supervisor、非 bridge）' },
  { term: '.url 台账', warn: true, desc: '磁盘 .url 指针文件；比 managed 多 = 残留（drift）→ 列表里的 orphaned' },
  { term: '抓取', warn: true, desc: 'tmux scrape 计数（不可靠）；与 registry 的 drift 是信号' }
];
