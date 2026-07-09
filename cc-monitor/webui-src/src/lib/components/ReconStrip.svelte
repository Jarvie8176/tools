<script lang="ts">
  import { store } from "../store.svelte";
  let rc = $derived(store.payload.recon);
  let chips = $derived.by(() => {
    if (!rc || rc.registry === undefined) return [];
    const scr = rc.scraped;
    return [
      ["registry ", rc.registry, false, "本地 registry 会话数（真值口径）"],
      ["managed ", rc.managed, false, "cc-session-managed"],
      ["env-spawned ", rc.rc_env_spawned, false, "rc-env-spawned（sdk-cli）"],
      ["individual ", rc.individual_cli, false, "individual-cli"],
      ["bridged ", rc.bridged, false, "cloud-bridged"],
      ["url-ledger ", rc.url_ledger, rc.url_ledger !== rc.managed, "supervisor .url 台账（可能含残留 > managed）"],
      ["scraped ", scr == null ? "—" : scr, scr != null && String(scr) !== String(rc.registry), "cc-session tmux 抓取（不可靠；vs registry 的 drift 是信号）"],
    ] as [string, string | number, boolean, string][];
  });
  function openSettings() { document.dispatchEvent(new CustomEvent("ccmon-settings")); }
</script>
<div style="display:flex;gap:7px;flex-wrap:wrap;align-items:center;padding:8px 14px;border-bottom:1px solid var(--bd2)">
  <button onclick={openSettings} title="来源核对：多口径会话计数；drift（url-ledger vs managed、scraped vs registry）是重点。点开图例。"
    style="font:500 11px var(--f-sans);color:var(--t3);background:none;border:0;cursor:pointer">来源核对 ⓘ</button>
  {#each chips as [k, v, drift, tip]}
    <span title={tip} style="font:500 11px var(--f-mono);padding:2px 8px;border-radius:5px;cursor:help;
      background:{drift ? 'var(--warnbg)' : 'var(--well)'};color:{drift ? 'var(--warn)' : 'var(--t2)'}">{k}<b style="color:{drift?'var(--warn)':'var(--t1)'}">{v}</b></span>
  {/each}
</div>
