<script>
  import { toggleExpand, startRename } from './state.svelte.js';
  import { CTX_TEXT } from './fmt.js';
  import StatusDot from './StatusDot.svelte';
  import ModelTag from './ModelTag.svelte';
  let { rows } = $props();
</script>

<!-- 排查密度（US3）：最新 prompt 全文流，无截断 -->
<div class="mx-auto w-full max-w-[760px] flex-1 pb-[90px]">
  {#each rows as r (r.id)}
    <div
      class="cursor-pointer border-b border-bd2 px-5 py-4"
      role="button" tabindex="0"
      onclick={() => toggleExpand(r.id)}
      onkeydown={(e) => e.key === 'Enter' && toggleExpand(r.id)}
    >
      <div class="mb-2.5 flex min-w-0 items-center gap-2.5">
        <StatusDot status={r.status} />
        <span class="min-w-0 truncate text-[14px] font-medium text-t1 {r.mono ? 'font-mono' : ''}">{r.dispName}</span>
        {#if !r.orphan}
          <button
            class="shrink-0 cursor-pointer text-[11px] text-info"
            onclick={(e) => { e.stopPropagation(); startRename(r.id, r.rawName); }}
          >✎</button>
        {/if}
        <ModelTag model={r.model} effort={r.effort} />
        <div class="flex-1"></div>
        <span class="shrink-0 font-mono text-[11px] font-medium {CTX_TEXT[r.level]} {r.level === 'dgr' ? 'font-bold' : ''}">{r.pct}%</span>
        <span class="shrink-0 font-mono text-[11px] font-medium text-t2">{r.idleStr}</span>
      </div>

      <div class="text-[13.5px] leading-[1.85] {r.orphan ? 'italic text-t4' : 'text-t2'}">{r.prompt}</div>

      {#if r.pInit}
        <div class="mt-2 truncate font-mono text-[11px] leading-[1.7] text-t4">开场：{r.pInit}</div>
      {/if}
    </div>
  {/each}
</div>
