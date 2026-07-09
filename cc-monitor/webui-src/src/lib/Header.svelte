<script>
  import { prefs, ui, setDensity, openSettings } from './state.svelte.js';
  import { feed } from './data.svelte.js';
  import ReconStrip from './ReconStrip.svelte';

  const DENSITIES = [
    { key: 'patrol', label: '巡检' },
    { key: 'standard', label: '标准' },
    { key: 'debug', label: '排查' }
  ];
</script>

<header class="border-b border-bd2 bg-panel px-4">
  <div class="flex h-[52px] items-center gap-3">
    <div class="font-mono text-[15px] font-bold text-t1">cc-monitor</div>

    {#if feed.connected}
      <div
        class="flex cursor-help items-center gap-1.5 rounded-full border border-bd2 bg-okbg px-2.5 py-[3px]"
        title="推送通道（SSE 单流）已连接：更新由服务端实时推送，非轮询"
      >
        <span class="ccpulse size-1.5 rounded-full bg-ok"></span>
        <span class="text-[11px] font-medium text-ok">实时</span>
      </div>
    {:else}
      <div
        class="flex cursor-help items-center gap-1.5 rounded-full border border-dgr bg-dgrbg px-2.5 py-[3px]"
        title="推送通道已断开，EventSource 自动重连中"
      >
        <span class="ccpulse-fast size-1.5 rounded-full bg-dgr"></span>
        <span class="text-[11px] font-medium text-dgr">已断开 · 重连中</span>
      </div>
    {/if}

    <div class="flex-1"></div>

    {#if prefs.reveal}
      <div
        class="flex cursor-help items-center rounded-full border border-info bg-infobg px-2.5 py-[3px] text-[11px] font-medium text-info"
        title="正在下发 prompt / title 原文 — 投屏/截图前到 ⚙ 设置里关掉"
      >原文</div>
    {/if}

    {#if !ui.isMobile}
      <div class="flex gap-0.5 rounded-lg border border-bd2 bg-chip p-0.5">
        {#each DENSITIES as d (d.key)}
          <button
            class="cursor-pointer rounded-md px-[13px] py-[5px] text-[12px] font-medium
                   {prefs.density === d.key ? 'bg-chip2 text-t1' : 'text-t3'}"
            onclick={() => setDensity(d.key)}
          >{d.label}</button>
        {/each}
      </div>
    {/if}

    <button
      class="flex size-8 cursor-pointer items-center justify-center rounded-lg border border-bd2 font-mono text-[15px] text-t3"
      onclick={openSettings}
      aria-label="设置"
    >⚙</button>
  </div>

  <ReconStrip />
</header>
