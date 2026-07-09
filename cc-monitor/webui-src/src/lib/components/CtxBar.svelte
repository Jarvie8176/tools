<script lang="ts">
  import type { Session } from "../types";
  import { store } from "../store.svelte";
  import { ctxPct, fmtK } from "../format";
  let { r }: { r: Session } = $props();
  let pct = $derived(ctxPct(r));
  let col = $derived(pct >= store.prefs.ctxDanger ? "var(--dgr)" : pct >= store.prefs.ctxWarn ? "var(--warn)" : "var(--ok)");
</script>
<span style="display:flex;align-items:center;gap:7px;white-space:nowrap">
  <span style="width:96px;height:8px;background:var(--well);border-radius:4px;overflow:hidden;flex:0 0 auto">
    <span style="display:block;height:100%;border-radius:4px;width:{Math.min(pct,100).toFixed(0)}%;background:{col}"></span>
  </span>
  <span class="mono" style="font-size:11.5px;color:{pct>=store.prefs.ctxWarn?col:'var(--t2)'};font-weight:{pct>=store.prefs.ctxDanger?700:500}">
    {fmtK(r.ctx)}/{fmtK(r.win)}{r.win_certain ? "" : "?"} ({pct.toFixed(0)}%)
  </span>
</span>
