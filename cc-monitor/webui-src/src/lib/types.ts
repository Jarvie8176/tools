export interface Session {
  session_id: string; u8: string; pid?: number; name: string; model: string;
  status: "busy" | "active" | "orphaned";
  ctx: number; peak_ctx?: number; win: number; win_certain: boolean;
  cum_input: number; cum_output: number; cum_cache?: number; full: boolean;
  bridge_id: string | null; bridge_short: string;
  custom_title: string | null; override_title: string | null;
  initial_prompt: string; last_prompt: string; session_effort: string | null;
  origin: string; bridged: boolean; last_activity_ts: number;
}
export interface Recon {
  registry: number; managed: number; rc_env_spawned: number; individual_cli: number;
  bridged: number; url_ledger: number; scraped: number | string | null;
}
export interface Payload {
  sessions: Session[]; prom: Record<string, string>; cc_session: boolean;
  effort: string | null; recon: Recon;
}
export type Density = "patrol" | "standard" | "debug";
export interface Prefs {
  density: Density; theme: "dark" | "light"; promptLines: number;
  ctxWarn: number; ctxDanger: number;
  cols: { prompt: boolean; ctx: boolean; idle: boolean };
}
