<script>
  // One inference endpoint. Reuses cc-monitor design primitives (CtxBar / ModelTag / StatusDot)
  // over the Prometheus-fed row model (see prom.py). Numeric-only payload — no free text.
  import CtxBar from './CtxBar.svelte';
  import ModelTag from './ModelTag.svelte';
  import StatusDot from './StatusDot.svelte';
  import { CTX_TEXT } from './fmt.js';

  let { r, cfg } = $props();

  const basename = (p) => (p ? p.split('/').pop() : null);

  // ctx-usage level from configurable thresholds (mirrors cc-monitor's ctx colouring).
  function level(pct) {
    if (pct == null) return 'off';
    if (pct >= cfg.ctx_crit_pct) return 'dgr';
    if (pct >= cfg.ctx_warn_pct) return 'warn';
    return 'ok';
  }
  function vlevel(pct) {
    if (pct == null) return 'off';
    if (pct >= cfg.vram_warn_pct) return 'warn';
    return 'ok';
  }
  const gb = (b) => (b == null ? '?' : (b / 1e9).toFixed(1) + 'G');

  const down = $derived(!r.up);
  const model = $derived(basename(r.served_id) || r.model_key || '—');
  const status = $derived(down ? 'orphaned' : r.active ? 'busy' : 'ready');
  const ctxVM = $derived({
    ctxLabel: r.ctx_effective ? `${r.ctx_used ?? '?'} / ${r.ctx_effective}` : '—',
    level: level(r.ctx_pct), pct: r.ctx_pct ?? 0
  });
  const vramVM = $derived({
    ctxLabel: r.vram_total ? `${gb(r.vram_used)} / ${gb(r.vram_total)}` : '—',
    level: vlevel(r.vram_pct), pct: r.vram_pct ?? 0
  });
  // G3: generation throughput below the floor = GPU dropped offload → flag red.
  const tpsLow = $derived(r.tok_s_gen != null && r.tok_s_gen < cfg.tps_floor);
</script>

<div class="rounded-xl border border-bd2 bg-card p-3.5 shadow-[var(--sh)] {down ? 'opacity-60' : ''}">
  <div class="mb-2.5 flex items-center gap-2">
    <StatusDot {status} />
    <span class="font-mono text-[13px] font-semibold text-t1">{r.host}</span>
    <div class="flex-1"></div>
    {#if down}
      <span class="rounded-[5px] bg-warnbg px-2 py-0.5 font-mono text-[10px] font-semibold text-warn">down</span>
    {:else}
      <ModelTag {model} />
    {/if}
  </div>

  {#if !down}
    <div class="mb-3 grid grid-cols-2 gap-x-4 gap-y-1 font-mono text-[11px]">
      <div class="flex justify-between">
        <span class="text-t3">tok/s gen</span>
        <span class="{tpsLow ? CTX_TEXT.dgr + ' font-bold' : 'text-t1'}">{r.tok_s_gen?.toFixed(1) ?? '?'}</span>
      </div>
      <div class="flex justify-between">
        <span class="text-t3">tok/s prompt</span>
        <span class="text-t2">{r.tok_s_prompt?.toFixed(0) ?? '?'}</span>
      </div>
      <div class="flex justify-between">
        <span class="text-t3">GPU</span>
        <span class="text-t2">{r.gpu_util != null ? Math.round(r.gpu_util * 100) + '%' : '?'}</span>
      </div>
      <div class="flex justify-between">
        <span class="text-t3">requests</span>
        <span class="text-t2">{r.active ?? '?'}{r.deferred ? ` +${r.deferred}q` : ''}</span>
      </div>
      <div class="flex justify-between">
        <span class="text-t3">swaps</span>
        <span class="text-t2">{r.swap_total}</span>
      </div>
      <div class="flex justify-between">
        <span class="text-t3">KV</span>
        <span class="text-t2">{r.kv_ratio != null ? (r.kv_ratio * 100).toFixed(1) + '%' : '?'}</span>
      </div>
    </div>

    <div class="mb-2">
      <div class="mb-1 font-mono text-[10.5px] font-medium text-t3">context (per-session)</div>
      <CtxBar r={ctxVM} />
    </div>
    <div>
      <div class="mb-1 font-mono text-[10.5px] font-medium text-t3">host VRAM (system-level)</div>
      <CtxBar r={vramVM} />
    </div>
  {/if}
</div>
