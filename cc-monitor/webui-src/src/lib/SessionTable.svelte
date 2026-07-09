<script>
  import { eff, toggleExpand, startRename } from './state.svelte.js';
  import StatusDot from './StatusDot.svelte';
  import CtxBar from './CtxBar.svelte';
  import Detail from './Detail.svelte';
  import ThinkPill from './ThinkPill.svelte';

  let { rows } = $props();

  const gridCols = $derived.by(() => {
    const c = eff.cols;
    const parts = ['96px', c.prompt ? '220px' : '1fr'];
    if (c.prompt) parts.push('1fr');
    if (c.ctx) parts.push(c.prompt ? '190px' : '240px');
    if (c.model) parts.push('128px');   // model + think level — right of context
    if (c.idle) parts.push('70px');
    parts.push('34px');
    return parts.join(' ');
  });
</script>

<div class="flex-1 pb-6">
  <div class="grid items-center gap-3.5 px-[18px] pb-2 pt-2.5 font-mono text-[10px] font-semibold tracking-[.08em] text-t4" style="grid-template-columns:{gridCols}">
    <div>STATUS</div>
    <div>SESSION</div>
    {#if eff.cols.prompt}<div>在干什么（最新 turn）</div>{/if}
    {#if eff.cols.ctx}<div>CONTEXT</div>{/if}
    {#if eff.cols.model}<div>MODEL</div>{/if}
    {#if eff.cols.idle}<div class="text-right">IDLE</div>{/if}
    <div></div>
  </div>

  {#each rows as r (r.id)}
    <div
      class="border-t border-bd2 border-l-2
             {r.expanded ? 'border-l-info bg-infobg' : r.orphan ? 'border-l-transparent bg-warnbg' : 'border-l-transparent bg-row'}"
    >
      <div
        class="grid cursor-pointer items-center gap-3.5 px-[18px] py-[11px]"
        style="grid-template-columns:{gridCols}"
        role="button" tabindex="0"
        onclick={() => toggleExpand(r.id)}
        onkeydown={(e) => e.key === 'Enter' && toggleExpand(r.id)}
      >
        <div class="flex items-center gap-[7px]"><StatusDot status={r.status} label /></div>

        <div class="min-w-0">
          <div class="flex items-center gap-1.5">
            <span class="truncate text-[13px] font-medium leading-[1.3] text-t1 {r.mono ? 'font-mono' : ''}">{r.dispName}</span>
            {#if !r.orphan}
              <button
                class="shrink-0 cursor-pointer text-[12px] text-info"
                onclick={(e) => { e.stopPropagation(); startRename(r.id, r.rawName); }}
                title="重命名"
              >✎</button>
            {/if}
          </div>
          <div class="mt-0.5 font-mono text-[10.5px] text-t4">{r.sub}</div>
        </div>

        {#if eff.cols.prompt}
          <div
            class="clamp text-[12.5px] leading-[1.55] {r.orphan ? 'italic text-t4' : 'text-t2'}"
            style="--lines:{eff.lines}"
          >{r.prompt}</div>
        {/if}

        {#if eff.cols.ctx}<CtxBar {r} />{/if}
        {#if eff.cols.model}
          <div class="flex min-w-0 items-center gap-1.5">
            <span class="truncate font-mono text-[11px] text-t2">{r.model}</span>
            <ThinkPill effort={r.effort} />
          </div>
        {/if}
        {#if eff.cols.idle}<div class="text-right font-mono text-[12px] font-medium text-t2">{r.idleStr}</div>{/if}

        <div class="text-center font-mono text-[11px] {r.expanded ? 'text-info' : 'text-t4'}">{r.expanded ? '▾' : '▸'}</div>
      </div>

      {#if r.expanded}
        <div class="px-[18px] pb-4 pt-0.5"><Detail {r} /></div>
      {/if}
    </div>
  {/each}
</div>
