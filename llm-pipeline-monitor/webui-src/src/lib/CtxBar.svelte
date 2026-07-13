<script>
  import { CTX_TEXT, CTX_BG } from './fmt.js';
  let { r, label = true, h = 6 } = $props();
  // A null pct means the series is absent — render "?" (not a confident "0%"), and a bounded,
  // clamped width so an over-budget (>100%) or missing value never overflows the track.
  const pct = $derived(r.pct == null ? null : Math.max(0, Math.min(100, r.pct)));
</script>

<div class="min-w-0">
  {#if label}
    <div class="mb-1 flex justify-between font-mono text-[11px] font-medium text-t2">
      <span>{r.ctxLabel}</span>
      <span class="{CTX_TEXT[r.level]} {r.level === 'dgr' ? 'font-bold' : ''}">{pct == null ? '?' : pct}%</span>
    </div>
  {/if}
  <div class="overflow-hidden rounded-[3px] bg-track" style="height:{h}px">
    <div class="rounded-[3px] {CTX_BG[r.level]}" style="height:{h}px;width:{pct ?? 0}%"></div>
  </div>
</div>
