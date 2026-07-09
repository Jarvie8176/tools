<script>
  import { prefs, ui } from './state.svelte.js';
  import Rename from './Rename.svelte';
  let { r } = $props();

  function copyUuid(e) {
    e.stopPropagation();
    try { navigator.clipboard.writeText(r.fullId || r.uuid.replace('…', '')); } catch {}
  }

  const meta = $derived([
    { k: '会话 ID', v: r.uuid, copy: true },
    { k: 'bridge ID', v: r.bridge },
    { k: '模型', v: r.modelStr },
    { k: '累计 tokens', v: r.cum },
    { k: '窗口容量', v: r.winStr },
    { k: '来源', v: r.origin }
  ]);
</script>

<!-- 操作置顶 → 最新 prompt 全文 → 开场 prompt 折叠 → meta 网格（设计规范 §1.5） -->
<div class="flex flex-col gap-2.5">
  <Rename {r} />

  <div class="rounded-lg border border-bd2 bg-well px-4 py-[13px]">
    <div class="mb-1.5 flex items-baseline gap-2">
      <span class="text-[10.5px] font-medium text-t3">最新 prompt</span>
      <span class="text-[10.5px] text-t4">· 全文</span>
    </div>
    <div class="text-[13px] leading-[1.85] {r.orphan ? 'italic text-t4' : 'text-t2'}">{r.prompt}</div>
    {#if !prefs.reveal && !r.orphan}
      <div class="mt-[7px] text-[11px] text-t4">已脱敏 — 在 ⚙ 设置中开启「下发原文」</div>
    {/if}
  </div>

  {#if r.pInit}
    <div>
      <button
        class="flex w-full cursor-pointer items-center gap-2 rounded-lg border border-bd2 bg-well px-4 py-[9px] text-left
               {ui.initOpen ? 'rounded-b-none' : ''}"
        onclick={(e) => { e.stopPropagation(); ui.initOpen = !ui.initOpen; }}
      >
        <span class="font-mono text-[10px] text-t4">{ui.initOpen ? '▾' : '▸'}</span>
        <span class="shrink-0 text-[11px] font-medium text-t3">开场 prompt</span>
        {#if !ui.initOpen}
          <span class="min-w-0 flex-1 truncate text-[11px] text-t4">{r.pInit}</span>
        {/if}
      </button>
      {#if ui.initOpen}
        <div class="rounded-b-lg border border-t-0 border-bd2 bg-well px-4 py-[11px] text-[12px] leading-[1.8] text-t2">{r.pInit}</div>
      {/if}
    </div>
  {/if}

  <div class="grid grid-cols-[repeat(auto-fit,minmax(230px,1fr))] gap-x-[18px] gap-y-[9px] rounded-lg border border-bd2 bg-well px-3.5 py-[11px]">
    {#each meta as m (m.k)}
      <div class="flex min-w-0 items-center gap-2">
        <span class="w-[66px] shrink-0 text-[10.5px] text-t4">{m.k}</span>
        <span class="min-w-0 truncate font-mono text-[11px] text-t2">{m.v}</span>
        {#if m.copy}
          <button class="shrink-0 cursor-pointer font-mono text-[10px] text-info" onclick={copyUuid} title="复制会话 ID">⧉</button>
        {/if}
      </div>
    {/each}
  </div>
</div>
