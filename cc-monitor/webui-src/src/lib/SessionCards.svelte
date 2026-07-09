<script>
  import { eff, toggleExpand } from './state.svelte.js';
  import { CTX_TEXT, CTX_BG } from './fmt.js';
  import ModelTag from './ModelTag.svelte';
  let { rows } = $props();

  const barColor = (r) => (r.orphan ? 'bg-warn' : r.level === 'dgr' ? 'bg-dgr' : r.busy ? 'bg-ok' : 'bg-info');
  const pill = (r) =>
    r.orphan
      ? { text: 'orphaned', cls: 'bg-warnbg text-warn' }
      : r.level === 'dgr'
        ? { text: `ctx ${r.pct}%`, cls: 'bg-dgrbg text-dgr' }
        : { text: r.status, cls: r.busy ? 'bg-okbg text-ok' : 'bg-infobg text-info' };
</script>

<div class="flex flex-1 flex-col gap-3 px-3 pb-[90px] pt-3.5">
  {#each rows as r (r.id)}
    {@const p = pill(r)}
    <div
      class="cursor-pointer overflow-hidden rounded-xl
             {r.orphan ? 'border border-dashed border-warn bg-warnbg' : 'border border-bd bg-card shadow-[var(--sh)]'}"
      role="button" tabindex="0"
      onclick={() => toggleExpand(r.id)}
      onkeydown={(e) => e.key === 'Enter' && toggleExpand(r.id)}
    >
      <div class="flex gap-[11px] px-3.5 pb-3 pt-[13px]">
        <div class="w-[3px] shrink-0 rounded-sm {barColor(r)}"></div>
        <div class="min-w-0 flex-1">
          <div class="flex items-center gap-2">
            <div class="flex min-w-0 flex-1 items-center gap-1.5">
              <span class="truncate text-[13.5px] font-medium text-t1 {r.mono ? 'font-mono' : ''}">{r.dispName}</span>
              {#if !r.orphan}<span class="shrink-0 text-[11px] text-info">✎</span>{/if}
            </div>
            <span class="shrink-0 rounded-[5px] px-2 py-0.5 font-mono text-[10px] font-semibold {p.cls}">{p.text}</span>
          </div>

          {#if eff.cols.prompt}
            <div class="clamp my-[7px] text-[12px] leading-[1.6] {r.orphan ? 'italic text-t4' : 'text-t2'}" style="--lines:{eff.lines}">{r.prompt}</div>
          {/if}

          <div class="flex items-center gap-2 {eff.cols.prompt ? '' : 'mt-2'}">
            {#if eff.cols.ctx && !r.orphan}
              <div class="h-[5px] flex-1 rounded-[3px] bg-track"><div class="h-[5px] rounded-[3px] {CTX_BG[r.level]}" style="width:{r.pct}%"></div></div>
              <span class="font-mono text-[10.5px] font-medium {CTX_TEXT[r.level]} {r.level === 'dgr' ? 'font-bold' : ''}">{r.pct}%</span>
            {/if}
            {#if eff.cols.model}<ModelTag model={r.model} effort={r.effort} />{/if}
            {#if eff.cols.idle}<span class="font-mono text-[10.5px] text-t4">空闲 {r.idleStr}</span>{/if}
          </div>
        </div>
      </div>
    </div>
  {/each}
</div>
