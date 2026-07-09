<script lang="ts">
  import type { Session } from "../types";
  import { store } from "../store.svelte";
  import SessionName from "./SessionName.svelte";
  import OriginBadge from "./OriginBadge.svelte";
  import CtxBar from "./CtxBar.svelte";
  import Idle from "./Idle.svelte";
  import RedactText from "./RedactText.svelte";
  import DetailPanel from "./DetailPanel.svelte";
  let { rows }: { rows: Session[] } = $props();
  let cols = $derived(store.prefs.cols);
  let span = $derived(2 + (cols.prompt ? 1 : 0) + (cols.ctx ? 1 : 0) + (cols.idle ? 1 : 0));
  function toggle(r: Session) { store.openId = store.openId === r.session_id ? null : r.session_id; }
</script>
<table style="border-collapse:collapse;width:100%">
  <thead><tr>
    <th>status</th><th>名称</th>
    {#if cols.prompt}<th>最新 prompt</th>{/if}
    {#if cols.ctx}<th>context</th>{/if}
    {#if cols.idle}<th>idle</th>{/if}
  </tr></thead>
  <tbody>
    {#each rows as r (r.session_id)}
      <tr class="srow {r.status}" onclick={() => toggle(r)}>
        <td><span class="mono" style="font-size:12px;white-space:nowrap;display:inline-flex;align-items:center;gap:6px"><span class="dot {r.status}"></span>{r.status}</span></td>
        <td><SessionName {r} /> <OriginBadge {r} /></td>
        {#if cols.prompt}<td><div class="clamp" style="color:var(--t2)"><RedactText text={r.last_prompt || "—"} /></div></td>{/if}
        {#if cols.ctx}<td><CtxBar {r} /></td>{/if}
        {#if cols.idle}<td><Idle {r} /></td>{/if}
      </tr>
      {#if store.openId === r.session_id}
        <tr><td colspan={span} style="background:var(--well)"><DetailPanel {r} /></td></tr>
      {/if}
    {/each}
  </tbody>
</table>
<style>
  th{text-align:left;padding:7px 10px;border-bottom:1px solid var(--bd2);font:600 10.5px var(--f-mono);color:var(--t3);text-transform:uppercase;letter-spacing:.4px}
  td{text-align:left;padding:7px 10px;border-bottom:1px solid var(--bd2);vertical-align:top}
  tr.srow{cursor:pointer}
  tr.srow:hover td{background:var(--row)}
  tr.busy td:first-child{box-shadow:inset 2px 0 0 var(--ok)}
  tr.orphaned td{background:var(--warnbg)}
  tr.orphaned td:first-child{box-shadow:inset 2px 0 0 var(--warn)}
</style>
