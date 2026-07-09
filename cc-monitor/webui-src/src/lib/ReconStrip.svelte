<script>
  import { ui } from './state.svelte.js';
  import { feed, RECON_LEGEND } from './data.svelte.js';

  // 真实 recon（stream.serialize）：registry/managed/rc_env_spawned/individual_cli/bridged/
  // url_ledger/scraped。drift = url_ledger≠managed（.url 残留）、scraped≠registry（抓取不可靠）。
  const chips = $derived.by(() => {
    const r = feed.recon;
    if (!r) return [];
    const scr = r.scraped;
    const ledgerDrift = r.url_ledger !== r.managed;
    const scrapeDrift = scr != null && String(scr) !== String(r.registry);
    return [
      { text: `registry ${r.registry}`, mono: true, title: RECON_LEGEND[0].desc },
      { text: `managed ${r.managed}`, mono: true, title: RECON_LEGEND[1].desc },
      { text: `env-spawned ${r.rc_env_spawned}`, mono: true, title: RECON_LEGEND[2].desc },
      { text: `individual ${r.individual_cli}`, mono: true, title: RECON_LEGEND[3].desc },
      { text: `${ledgerDrift ? '⚠ ' : ''}.url 台账 ${r.url_ledger}${ledgerDrift ? ` · 多 ${r.url_ledger - r.managed} 条未对上` : ''}`, warn: ledgerDrift, title: RECON_LEGEND[4].desc },
      { text: `抓取 ${scr == null ? '—' : scr}/${r.registry}`, warn: scrapeDrift, title: RECON_LEGEND[5].desc }
    ];
  });
</script>

<div class="flex items-center gap-[7px] overflow-x-auto pb-2.5 font-mono text-[10.5px] font-medium">
  <button class="shrink-0 cursor-pointer font-sans text-t4" onclick={() => (ui.reconOpen = !ui.reconOpen)}>来源核对</button>

  {#each chips as c (c.text)}
    <span
      class="shrink-0 cursor-help rounded-[5px] px-2 py-0.5
             {c.warn ? 'border border-warn bg-warnbg font-sans text-warn' : 'bg-chip text-t2'}
             {c.mono ? '' : 'font-sans'}"
      title={c.title}
    >{c.text}</span>
  {/each}

  <button
    class="flex size-4 shrink-0 cursor-pointer items-center justify-center rounded-full border border-bd2 font-mono text-[10px] font-medium
           {ui.reconOpen ? 'text-info' : 'text-t4'}"
    onclick={() => (ui.reconOpen = !ui.reconOpen)}
    title="点按查看每项含义"
  >i</button>

  <div class="flex-1"></div>
  <span class="shrink-0 text-t4">本地 tick · 无 wall-clock</span>
</div>

{#if ui.reconOpen}
  <div class="mb-2.5 grid grid-cols-[repeat(auto-fit,minmax(250px,1fr))] gap-x-5 gap-y-[7px] rounded-lg border border-bd2 bg-well px-3.5 py-[11px]">
    {#each RECON_LEGEND as l (l.term)}
      <div class="flex min-w-0 gap-2">
        <span class="w-[86px] shrink-0 font-mono text-[10.5px] font-medium {l.warn ? 'text-warn' : 'text-t2'}">{l.term}</span>
        <span class="text-[11px] leading-[1.6] text-t3">{l.desc}</span>
      </div>
    {/each}
  </div>
{/if}
