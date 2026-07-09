<script lang="ts">
  import { onMount } from "svelte";
  import { store } from "../store.svelte";
  import type { Session, Density } from "../types";
  import ReconStrip from "./ReconStrip.svelte";
  import StatCards from "./StatCards.svelte";
  import SessionTable from "./SessionTable.svelte";
  import CardList from "./CardList.svelte";
  import DetailPanel from "./DetailPanel.svelte";
  import SettingsDrawer from "./SettingsDrawer.svelte";
  import { titleOf } from "../format";

  let mobile = $state(false);
  let settingsOpen = $state(false);

  const DENSITIES: [Density, string, string][] = [
    ["patrol", "巡检", "巡检：统计卡 + 精简列表，聚焦需关注"],
    ["standard", "标准", "标准：桌面窄表格 / 手机卡片"],
    ["debug", "排查", "排查：单列 feed，prompt 全文无截断"],
  ];

  let base = $derived(
    store.sessions.filter((r) => {
      const q = store.filter.trim().toLowerCase();
      if (!q) return true;
      return [r.name, r.custom_title, r.override_title, r.initial_prompt, r.last_prompt, r.model, r.u8, r.origin]
        .some((v) => (v || "").toLowerCase().includes(q));
    }),
  );
  let rows = $derived.by(() => {
    let rs = base;
    if (store.prefs.density === "patrol") {
      const pf = store.patrolFilter;
      rs = rs.filter((r) =>
        pf === "busy" ? r.status === "busy" : pf === "active" ? r.status === "active"
        : pf === "attention" ? store.needsAttention(r) : true);
    }
    return [...rs].sort((a, b) =>
      (a.status !== "busy" ? 1 : 0) - (b.status !== "busy" ? 1 : 0) || (b.last_activity_ts || 0) - (a.last_activity_ts || 0));
  });
  let useSheet = $derived(!(store.prefs.density === "standard" && !mobile));
  let sheetRow = $derived.by((): Session | undefined =>
    useSheet && store.openId ? store.sessions.find((s) => s.session_id === store.openId) : undefined);

  onMount(() => {
    const onResize = () => (mobile = window.innerWidth < 720);
    onResize();
    window.addEventListener("resize", onResize);
    document.body.classList.toggle("light", store.prefs.theme === "light");
    $effect.root(() => {
      $effect(() => { document.body.classList.toggle("light", store.prefs.theme === "light"); });
      $effect(() => { document.documentElement.style.setProperty("--pl", String(store.prefs.promptLines)); });
    });
    const onSettings = () => (settingsOpen = true);
    document.addEventListener("ccmon-settings", onSettings);
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") { store.openId = null; settingsOpen = false; } };
    document.addEventListener("keydown", onKey);
    store.loadConfig();
    store.connect();
    const iv = setInterval(() => (store.tick = store.tick + 1), 1000);
    return () => { clearInterval(iv); window.removeEventListener("resize", onResize);
      document.removeEventListener("ccmon-settings", onSettings); document.removeEventListener("keydown", onKey); };
  });
</script>

<header>
  <h1>cc-monitor</h1>
  <span class="mono" style="font-size:11px;color:var(--t3);margin-left:6px">effort {store.payload.effort || "?"} · {store.sessions.length} 会话{store.payload.cc_session ? " · RC " + (store.payload.prom.rc_connected === "1" ? "connected" : "DOWN/?") : ""}</span>
  <span style="flex:1"></span>
  <span class="badge" style="background:{store.connected ? 'var(--okbg)' : 'var(--dgrbg)'};color:{store.connected ? 'var(--ok)' : 'var(--dgr)'}">{store.connected ? "实时" : "重连中…"}</span>
  {#if store.revealOn}<span class="badge" style="background:var(--warnbg);color:var(--warn)" title="服务端已下发未脱敏原文">原文</span>{/if}
  {#if !mobile}
    <div class="seg">
      {#each DENSITIES as [d, label, tip]}
        <button class:on={store.prefs.density === d} onclick={() => store.setDensity(d)} title={tip}>{label}</button>
      {/each}
    </div>
  {/if}
  <button class="ico" onclick={() => (settingsOpen = true)} title="设置">⚙</button>
</header>

<ReconStrip />

<div style="padding:8px 14px;display:flex;gap:10px;align-items:center;flex-wrap:wrap">
  <input placeholder="过滤 名称 / prompt / model / uuid" value={store.filter}
    oninput={(e) => (store.filter = e.currentTarget.value)}
    style="min-width:min(260px,60vw);flex:1;background:var(--row);color:var(--t2);border:1px solid var(--bd);border-radius:7px;padding:5px 9px;font-size:12.5px" />
  <span class="mono" style="font-size:11px;color:var(--t3)">{rows.length} 显示 / {store.sessions.length} 会话</span>
</div>

{#if store.prefs.density === "patrol"}<StatCards rows={base} />{/if}

<main>
  {#if store.prefs.density === "debug"}
    <CardList {rows} feed={true} />
  {:else if store.prefs.density === "standard" && !mobile}
    <SessionTable {rows} />
  {:else}
    <CardList {rows} />
  {/if}
</main>

{#if mobile}
  <nav class="mbar">
    {#each DENSITIES as [d, label]}
      <button class:on={store.prefs.density === d} onclick={() => store.setDensity(d)}>{label}</button>
    {/each}
  </nav>
{/if}

{#if useSheet && sheetRow}
  <div class="backdrop show" onclick={() => (store.openId = null)} role="presentation"></div>
  <div class="sheet show">
    <div style="display:flex;justify-content:space-between;align-items:center;padding:11px 14px;border-bottom:1px solid var(--bd2)">
      <b style="font:500 13.5px var(--f-sans);color:var(--t1)">{titleOf(sheetRow).t || sheetRow.name || sheetRow.u8 || "详情"}</b>
      <button class="ico" onclick={() => (store.openId = null)}>✕</button>
    </div>
    <DetailPanel r={sheetRow} />
  </div>
{/if}

<SettingsDrawer bind:open={settingsOpen} />

<style>
  header{position:sticky;top:0;z-index:5;background:var(--panel);border-bottom:1px solid var(--bd2);padding:9px 14px;display:flex;align-items:center;gap:12px;flex-wrap:wrap}
  h1{font:600 15px var(--f-sans);color:var(--info);margin:0;letter-spacing:.2px}
  main{padding:6px 14px 24px}
  .badge{font:600 10.5px var(--f-mono);padding:2px 8px;border-radius:10px}
  .seg{display:inline-flex;border:1px solid var(--bd);border-radius:8px;overflow:hidden}
  .seg button{background:transparent;color:var(--t3);border:0;padding:5px 11px;font:500 12.5px var(--f-sans);cursor:pointer}
  .seg button.on{background:var(--infobg);color:var(--info)}
  .ico{background:transparent;border:1px solid var(--bd);color:var(--t2);border-radius:7px;width:32px;height:30px;font-size:15px;cursor:pointer}
  .mbar{position:fixed;left:0;right:0;bottom:0;background:var(--panel);border-top:1px solid var(--bd);display:flex;z-index:15}
  .mbar button{flex:1;min-height:46px;background:transparent;border:0;color:var(--t3);font:500 12.5px var(--f-sans);cursor:pointer}
  .mbar button.on{color:var(--info)}
  .backdrop{position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:20}
  .sheet{position:fixed;left:0;right:0;bottom:0;max-width:600px;margin:0 auto;background:var(--panel);border:1px solid var(--bd);border-bottom:0;border-radius:16px 16px 0 0;z-index:22;max-height:86vh;overflow:auto}
</style>
