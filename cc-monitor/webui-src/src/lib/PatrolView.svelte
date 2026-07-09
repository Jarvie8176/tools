<script>
  import { ui, toggleExpand } from './state.svelte.js';
  import { CTX_TEXT, CTX_BG } from './fmt.js';
  import StatusDot from './StatusDot.svelte';
  let { rows } = $props();

  const attn = $derived(rows.filter((r) => r.attn).sort((a, b) => (b.orphan ? -1 : b.pct) - (a.orphan ? -1 : a.pct)));
  const busyN = $derived(rows.filter((r) => r.status === 'busy').length);
  const activeN = $derived(rows.filter((r) => r.status === 'active').length);
  const list = $derived(rows.filter((r) => r.status === (ui.patrolFilter === 'busy' ? 'busy' : 'active')));
  const attnColor = $derived(attn.some((r) => r.attnLevel === 'dgr') ? 'text-dgr' : attn.length ? 'text-warn' : 'text-t3');

  const cardBd = (key, on) =>
    !on ? 'border-bd2'
    : key === 'busy' ? 'border-ok'
    : key === 'active' ? 'border-info'
    : attn.length ? 'border-warn' : 'border-t4';
</script>

<!-- 巡检总览：统计卡 = 可点击过滤，默认「需关注」 -->
<div class="mx-auto w-full max-w-[820px] flex-1 px-4 pb-[90px] pt-3.5">
  <div class="grid grid-cols-3 gap-2.5">
    {#each [
      { key: 'busy', label: '生成中', n: busyN, cls: 'text-ok' },
      { key: 'active', label: '可达待命', n: activeN, cls: 'text-info' },
      { key: 'attn', label: '需关注', n: attn.length, cls: attnColor }
    ] as c (c.key)}
      <button
        class="cursor-pointer rounded-[10px] border bg-row px-3.5 py-3 text-left {cardBd(c.key, ui.patrolFilter === c.key)}"
        onclick={() => { ui.patrolFilter = c.key; ui.expanded = null; }}
      >
        <div class="font-mono text-[9.5px] font-semibold tracking-[.08em] text-t4">{c.label}</div>
        <div class="mt-1 font-mono text-[22px] font-bold {c.cls}">{c.n}</div>
      </button>
    {/each}
  </div>

  {#if ui.patrolFilter === 'attn'}
    {#if attn.length === 0}
      <div class="mt-4 rounded-[10px] border border-bd2 bg-row px-4 py-[22px] text-center text-[12px] text-t3">当前没有需要关注的 session</div>
    {:else}
      <div class="mx-0.5 mb-2 mt-4 font-mono text-[10px] font-semibold tracking-[.08em] text-t4">需关注</div>
      <div class="flex flex-col gap-2">
        {#each attn as r (r.id)}
          <button
            class="flex cursor-pointer gap-[11px] rounded-[10px] border border-bd2 bg-row px-3.5 py-[11px] text-left"
            onclick={() => toggleExpand(r.id)}
          >
            <div class="w-[3px] shrink-0 rounded-sm {r.attnLevel === 'dgr' ? 'bg-dgr' : 'bg-warn'}"></div>
            <div class="min-w-0 flex-1">
              <div class="flex items-center gap-2">
                <span class="min-w-0 truncate text-[13px] font-medium text-t1 {r.mono ? 'font-mono' : ''}">{r.dispName}</span>
                <div class="flex-1"></div>
                <span class="shrink-0 text-[11px] font-medium {r.attnLevel === 'dgr' ? 'text-dgr' : 'text-warn'}">{r.attnReason}</span>
              </div>
              <div class="mt-2 flex items-center gap-2">
                <div class="h-[5px] flex-1 rounded-[3px] bg-track"><div class="h-[5px] rounded-[3px] {CTX_BG[r.level]}" style="width:{r.pct}%"></div></div>
                <span class="shrink-0 font-mono text-[10.5px] font-medium {CTX_TEXT[r.level]}">{r.pct}%</span>
                <span class="shrink-0 font-mono text-[10.5px] text-t4">空闲 {r.idleStr}</span>
              </div>
            </div>
          </button>
        {/each}
      </div>
    {/if}
  {:else}
    <div class="mx-0.5 mb-2 mt-4 font-mono text-[10px] font-semibold tracking-[.08em] text-t4">{ui.patrolFilter === 'busy' ? '生成中' : '可达待命'}</div>
    <div class="overflow-hidden rounded-[10px] border border-bd2 bg-row">
      {#each list as r (r.id)}
        <button
          class="flex w-full cursor-pointer items-center gap-2.5 border-b border-bd2 px-3.5 py-3 text-left last:border-b-0"
          onclick={() => toggleExpand(r.id)}
        >
          <StatusDot status={r.status} />
          <span class="min-w-0 truncate text-[12.5px] font-medium text-t1 {r.mono ? 'font-mono' : ''}">{r.dispName}</span>
          <span class="shrink-0 font-mono text-[10px] font-semibold {r.busy ? 'text-ok' : 'text-info'}">{r.status}</span>
          <div class="flex-1"></div>
          <div class="h-1 w-[110px] shrink-0 rounded-sm bg-track"><div class="h-1 rounded-sm {CTX_BG[r.level]}" style="width:{r.pct}%"></div></div>
          <span class="w-[34px] shrink-0 text-right font-mono text-[10.5px] font-medium text-t2">{r.pct}%</span>
          <span class="w-[54px] shrink-0 text-right font-mono text-[10.5px] text-t4">{r.idleStr}</span>
        </button>
      {/each}
    </div>
  {/if}
</div>
