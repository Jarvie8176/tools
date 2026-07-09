<script lang="ts">
  import type { Session } from "../types";
  import { store } from "../store.svelte";
  import SessionName from "./SessionName.svelte";
  import OriginBadge from "./OriginBadge.svelte";
  import CtxBar from "./CtxBar.svelte";
  import Idle from "./Idle.svelte";
  import RedactText from "./RedactText.svelte";
  let { rows, feed = false }: { rows: Session[]; feed?: boolean } = $props();
</script>
<div style="display:flex;flex-direction:column;gap:9px">
  {#each rows as r (r.session_id)}
    <div class="scard {r.status}" onclick={() => (store.openId = r.session_id)} role="button" tabindex="0"
      onkeydown={(e) => { if (e.key === 'Enter') store.openId = r.session_id; }}>
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">
        <span class="dot {r.status}"></span><SessionName {r} /><OriginBadge {r} /><span style="flex:1"></span>
        {#if feed}<span style="font-size:11px;color:var(--t3)">点开详情</span>{/if}
      </div>
      {#if feed}
        <div style="font:600 10.5px var(--f-mono);color:var(--t3);text-transform:uppercase;letter-spacing:.4px;margin-bottom:3px">最新 prompt</div>
        <div style="background:var(--row);border:1px solid var(--bd2);border-radius:8px;padding:9px 11px;line-height:1.75;white-space:pre-wrap;word-break:break-word;color:var(--t1);max-width:760px"><RedactText text={r.last_prompt || "—"} /></div>
      {:else}
        <div class="clamp" style="color:var(--t2)"><RedactText text={r.last_prompt || "—"} /></div>
      {/if}
      <div style="display:flex;gap:10px;align-items:center;margin-top:7px"><CtxBar {r} /><Idle {r} /></div>
    </div>
  {/each}
</div>
<style>
  .scard{background:var(--card);border:1px solid var(--bd2);border-radius:11px;padding:11px 13px;box-shadow:var(--sh);cursor:pointer}
  .scard.orphaned{border-color:var(--warn)}
</style>
