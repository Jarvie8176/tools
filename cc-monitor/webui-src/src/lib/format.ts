import type { Session } from "./types";

export const REDACT_MARK = "[redacted]";
export const ORIGIN_ABBR: Record<string, string> = {
  "cc-session-managed": "mgd", "rc-env-spawned": "env", "individual-cli": "cli",
};

export const fmtK = (n: number): string => {
  n = n || 0;
  if (n >= 1e6) return (n / 1e6).toFixed(1) + "M";
  return n >= 1000 ? (n / 1000).toFixed(1) + "k" : String(n);
};
export const shortModel = (m: string): string => (m || "-").replace("claude-", "");
export const fmtIdle = (s: number): string => {
  s = Math.max(0, Math.floor(s));
  if (s < 60) return s + "s";
  if (s < 3600) return Math.floor(s / 60) + "m" + (s % 60) + "s";
  return Math.floor(s / 3600) + "h" + Math.floor((s % 3600) / 60) + "m";
};
export const nowS = (): number => Date.now() / 1000;
export const isRedacted = (v: string | null): boolean => v === REDACT_MARK;

export interface TitleInfo { t: string; src: "override" | "custom" | "cloud-side"; }
export const titleOf = (r: Session): TitleInfo => {
  if (r.override_title) return { t: r.override_title, src: "override" };
  if (r.custom_title) return { t: r.custom_title, src: "custom" };
  return { t: "", src: "cloud-side" };
};
export const ctxPct = (r: Session): number => (r.win ? (100 * (r.ctx || 0)) / r.win : 0);
export const originAbbr = (r: Session): string =>
  (ORIGIN_ABBR[r.origin] || "?") + (r.bridged ? "·b" : "");
