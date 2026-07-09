<script>
  import { CTX_TEXT, CTX_BG } from './fmt.js';
  let { r, label = true, h = 6 } = $props();
</script>

<div class="min-w-0">
  {#if label}
    <div class="mb-1 flex justify-between font-mono text-[11px] font-medium text-t2">
      <span>{r.ctxLabel}</span>
      <span class="{CTX_TEXT[r.level]} {r.level === 'dgr' ? 'font-bold' : ''}">{r.pct}%</span>
    </div>
  {/if}
  <div class="rounded-[3px] bg-track" style="height:{h}px">
    <div class="rounded-[3px] {CTX_BG[r.level]}" style="height:{h}px;width:{r.pct}%"></div>
  </div>
</div>
