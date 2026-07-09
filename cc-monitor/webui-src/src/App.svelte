<script>
  import { prefs, ui, setDensity, init } from './lib/state.svelte.js';
  import { buildRows } from './lib/rows.svelte.js';
  import Header from './lib/Header.svelte';
  import SessionTable from './lib/SessionTable.svelte';
  import SessionCards from './lib/SessionCards.svelte';
  import FeedList from './lib/FeedList.svelte';
  import PatrolView from './lib/PatrolView.svelte';
  import Sheet from './lib/Sheet.svelte';
  import Settings from './lib/Settings.svelte';

  // 主题：整套 CSS 变量随 data-theme 切换（设计规范 §1.2）
  $effect(() => {
    document.documentElement.dataset.theme = prefs.theme;
  });

  // 断点 720px（设计规范 §1.5）
  $effect(() => {
    const mq = window.matchMedia('(max-width: 719px)');
    const apply = () => (ui.isMobile = mq.matches);
    apply();
    mq.addEventListener('change', apply);
    return () => mq.removeEventListener('change', apply);
  });

  // idle 本地 tick（硬约束：payload 无 wall-clock 字段）
  $effect(() => {
    const t = setInterval(() => (ui.now = Date.now()), 1000);
    return () => clearInterval(t);
  });

  // 接入真实数据：加载服务端 reveal 缺省 + 打开 SSE /api/stream
  $effect(() => {
    const es = init();
    return () => es && es.close && es.close();
  });

  const rows = $derived(buildRows());
  const mode = $derived(
    prefs.density === 'debug' ? 'feed'
    : prefs.density === 'patrol' ? 'patrol'
    : ui.isMobile ? 'cards' : 'table'
  );
  const sheetRow = $derived(mode !== 'table' ? rows.find((r) => r.expanded) : null);

  const DENSITIES = [
    { key: 'patrol', label: '巡检' },
    { key: 'standard', label: '标准' },
    { key: 'debug', label: '排查' }
  ];
</script>

<div class="flex min-h-screen flex-col bg-bg" data-screen-label="dashboard">
  <Header />

  {#if mode === 'table'}
    <SessionTable {rows} />
  {:else if mode === 'cards'}
    <SessionCards {rows} />
  {:else if mode === 'feed'}
    <FeedList {rows} />
  {:else}
    <PatrolView {rows} />
  {/if}

  {#if ui.isMobile}
    <div class="fixed inset-x-0 bottom-0 z-40 border-t border-bd2 bg-panel px-3 pb-3.5 pt-2.5">
      <div class="flex gap-[3px] rounded-[9px] border border-bd2 bg-chip p-[3px]">
        {#each DENSITIES as d (d.key)}
          <button
            class="flex-1 cursor-pointer rounded-[7px] py-[9px] text-center text-[13px] font-medium
                   {prefs.density === d.key ? 'bg-chip2 text-t1' : 'text-t3'}"
            onclick={() => setDensity(d.key)}
          >{d.label}</button>
        {/each}
      </div>
    </div>
  {/if}

  {#if sheetRow}
    <Sheet r={sheetRow} />
  {/if}

  {#if ui.settingsOpen}
    <Settings />
  {/if}
</div>
