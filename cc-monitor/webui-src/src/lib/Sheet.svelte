<script>
  import { closeSheet } from './state.svelte.js';
  import Detail from './Detail.svelte';
  import CtxBar from './CtxBar.svelte';
  let { r } = $props();

  const pill = $derived(
    r.orphan
      ? { text: 'orphaned', cls: 'bg-warnbg text-warn' }
      : r.level === 'dgr'
        ? { text: `ctx ${r.pct}%`, cls: 'bg-dgrbg text-dgr' }
        : { text: r.status, cls: r.busy ? 'bg-okbg text-ok' : 'bg-infobg text-info' }
  );
</script>

<!-- 卡片 / feed / 巡检模式的下钻容器：底部 sheet -->
<div
  class="fixed inset-0 z-50 flex items-end justify-center bg-black/55"
  role="button" tabindex="-1"
  onclick={closeSheet}
  onkeydown={(e) => e.key === 'Escape' && closeSheet()}
>
  <div
    class="cc-scroll max-h-[82vh] w-full max-w-[600px] overflow-auto rounded-t-2xl border border-b-0 border-bd bg-panel px-[18px] pb-[26px] pt-4"
    role="dialog" tabindex="-1"
    onclick={(e) => e.stopPropagation()}
    onkeydown={(e) => e.stopPropagation()}
  >
    <div class="mb-3 flex items-center gap-2.5">
      <span class="min-w-0 truncate text-[14px] font-medium text-t1 {r.mono ? 'font-mono' : ''}">{r.dispName}</span>
      <span class="shrink-0 rounded-[5px] px-2 py-0.5 font-mono text-[10px] font-semibold {pill.cls}">{pill.text}</span>
      <div class="flex-1"></div>
      <button
        class="flex size-[30px] cursor-pointer items-center justify-center rounded-lg border border-bd2 font-mono text-[13px] text-t3"
        onclick={closeSheet} aria-label="关闭"
      >✕</button>
    </div>

    <Detail {r} />

    <div class="mb-1 mt-3 flex justify-between font-mono text-[11px] font-medium text-t2">
      <span>context {r.ctxLabel}</span>
    </div>
    <CtxBar {r} label={false} />
  </div>
</div>
