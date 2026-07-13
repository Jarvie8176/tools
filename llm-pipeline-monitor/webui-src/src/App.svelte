<script>
  import { feed, connectFeed, cfg, loadCfg, saveCfg } from './lib/data.svelte.js';
  import EndpointCard from './lib/EndpointCard.svelte';
  import DualRange from './lib/DualRange.svelte';
  import Stepper from './lib/Stepper.svelte';

  let theme = $state('dark');
  let showSettings = $state(false);

  // Theme: the whole CSS-variable set swaps on data-theme (reused design system).
  $effect(() => { document.documentElement.dataset.theme = theme; });

  $effect(() => {
    loadCfg();
    const es = connectFeed();
    return () => es.close();
  });

  const clampWarn = (v) => saveCfg({ ctx_warn_pct: Math.min(v, cfg.ctx_crit_pct) });
  const clampCrit = (v) => saveCfg({ ctx_crit_pct: Math.max(v, cfg.ctx_warn_pct) });
</script>

<div class="mx-auto max-w-[1100px] px-4 py-4">
  <header class="mb-4 flex items-center gap-2.5">
    <span class="text-[15px] font-semibold text-t1">LLM pipeline</span>
    <span class="font-mono text-[11px] text-t4">inference endpoints</span>
    <div class="flex-1"></div>
    <span class="flex items-center gap-1.5 font-mono text-[11px]">
      <span class="size-2 rounded-full {feed.connected ? 'bg-ok' : 'bg-dgr'}"></span>
      <span class="text-t3">{feed.connected ? 'live' : 'offline'}</span>
    </span>
    <button class="rounded-lg border border-bd2 px-2 py-1 font-mono text-[11px] text-t3"
      onclick={() => (theme = theme === 'dark' ? 'light' : 'dark')} aria-label="theme">
      {theme === 'dark' ? '☾' : '☀'}
    </button>
    <button class="rounded-lg border border-bd2 px-2 py-1 font-mono text-[11px] text-t3"
      onclick={() => (showSettings = !showSettings)} aria-label="settings">⚙</button>
  </header>

  {#if !feed.ok}
    <div class="mb-3 rounded-lg border border-bd2 bg-warnbg px-3 py-2 font-mono text-[11px] text-warn">
      upstream unreachable{feed.error ? `: ${feed.error}` : ''}
    </div>
  {/if}

  {#if feed.rows.length === 0 && feed.ok}
    <div class="rounded-lg border border-bd2 bg-panel px-3 py-6 text-center font-mono text-[12px] text-t3">
      no llm_endpoint_* series in upstream
    </div>
  {:else}
    <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
      {#each feed.rows as r (r.host)}
        <EndpointCard {r} {cfg} />
      {/each}
    </div>
  {/if}

  {#if showSettings}
    <div class="mt-4 rounded-xl border border-bd2 bg-panel p-4">
      <div class="mb-2 font-mono text-[11px] font-semibold text-t2">context 阈值 (per-session %)</div>
      <DualRange warn={cfg.ctx_warn_pct} danger={cfg.ctx_crit_pct} setWarn={clampWarn} setDanger={clampCrit} />
      <div class="mt-4 flex items-center gap-3">
        <span class="font-mono text-[11px] text-t3">tok/s floor (G3)</span>
        <Stepper value={cfg.tps_floor}
          dec={() => saveCfg({ tps_floor: Math.max(0, cfg.tps_floor - 5) })}
          inc={() => saveCfg({ tps_floor: cfg.tps_floor + 5 })} />
        <span class="font-mono text-[11px] text-t3">VRAM warn %</span>
        <Stepper value={cfg.vram_warn_pct}
          dec={() => saveCfg({ vram_warn_pct: Math.max(0, cfg.vram_warn_pct - 5) })}
          inc={() => saveCfg({ vram_warn_pct: Math.min(100, cfg.vram_warn_pct + 5) })} />
      </div>
    </div>
  {/if}
</div>
