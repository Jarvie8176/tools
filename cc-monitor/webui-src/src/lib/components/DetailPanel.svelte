<script lang="ts">
  import type { Session } from "../types";
  import { store } from "../store.svelte";
  import { titleOf, shortModel, fmtK } from "../format";
  import RedactText from "./RedactText.svelte";
  import OriginBadge from "./OriginBadge.svelte";
  let { r }: { r: Session } = $props();
  let ti = $derived(titleOf(r));
  let renaming = $state(false);
  let draft = $state("");
  function startRename() { draft = ti.t || ""; renaming = true; }
  function commit() { store.rename(r.session_id || r.bridge_id || "", draft.trim()); renaming = false; }
  function onKey(e: KeyboardEvent) {
    e.stopPropagation();
    if (e.key === "Enter") commit();
    else if (e.key === "Escape") renaming = false;
  }
  let meta = $derived([
    ["会话 ID", (r.u8 || "") + (r.session_id ? `  (${r.session_id})` : "")],
    ["origin", (r.origin || "—") + (r.bridged ? " · bridged" : "")],
    ["bridge", r.bridge_id || "—"],
    ["model", shortModel(r.model)],
    ["s-effort", r.session_effort || "—"],
    ["累计 tok", `↓${fmtK(r.cum_input)} ↑${fmtK(r.cum_output)}`],
    ["窗口", fmtK(r.win) + (r.win_certain ? "" : " (?)")],
    ["状态", r.status],
  ] as [string, string][]);
</script>

<div style="padding:12px 14px;display:flex;flex-direction:column;gap:10px;border-left:2px solid var(--info)">
  <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
    {#if r.status === "orphaned"}
      <span style="color:var(--t4)">orphaned — 不可重命名</span>
    {:else if renaming}
      <input value={draft} oninput={(e) => (draft = e.currentTarget.value)} onkeydown={onKey}
        placeholder="Enter 保存 / 空值清除" style="min-width:220px;background:var(--row);color:var(--t2);
        border:1px solid var(--bd);border-radius:7px;padding:5px 9px;font-size:12.5px" />
      <button onclick={commit} class="btn-pri">保存</button>
    {:else}
      <button onclick={startRename} class="btn-pri">{ti.src === "cloud-side" ? "命名" : "重命名"}</button>
    {/if}
    <OriginBadge {r} />
  </div>

  <div>
    <div class="plabel">最新 prompt</div>
    <div class="ptext"><RedactText text={r.last_prompt || "—"} /></div>
  </div>
  <details>
    <summary style="cursor:pointer;font:500 11.5px var(--f-sans);color:var(--t3)">开场 prompt</summary>
    <div class="ptext" style="margin-top:6px"><RedactText text={r.initial_prompt || "—"} /></div>
  </details>

  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:7px">
    {#each meta as [k, v]}
      <div style="background:var(--row);border:1px solid var(--bd2);border-radius:8px;padding:8px 11px;display:flex;gap:8px">
        <span style="font:500 10.5px var(--f-sans);color:var(--t3);flex:0 0 66px">{k}</span>
        <span class="mono" title={v} style="font-size:12px;color:var(--t2);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{v}</span>
      </div>
    {/each}
  </div>
</div>

<style>
  .btn-pri{background:var(--infobg);border:1px solid var(--info);color:var(--info);border-radius:7px;padding:5px 11px;font:500 12px var(--f-sans);cursor:pointer}
  .plabel{font:600 10.5px var(--f-mono);color:var(--t3);text-transform:uppercase;letter-spacing:.4px;margin-bottom:3px}
  .ptext{background:var(--row);border:1px solid var(--bd2);border-radius:8px;padding:9px 11px;line-height:1.75;white-space:pre-wrap;word-break:break-word;color:var(--t1)}
</style>
