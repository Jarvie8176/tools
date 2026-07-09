<script lang="ts">
  import type { Session } from "../types";
  import { store } from "../store.svelte";
  let { rows }: { rows: Session[] } = $props();
  let defs = $derived([
    ["busy", "生成中", rows.filter((r) => r.status === "busy").length],
    ["active", "可达待命", rows.filter((r) => r.status === "active").length],
    ["attention", "需关注", rows.filter((r) => store.needsAttention(r)).length],
  ] as ["busy" | "active" | "attention", string, number][]);
  function pick(k: "busy" | "active" | "attention") { store.patrolFilter = store.patrolFilter === k ? null : k; }
</script>
<div style="display:flex;gap:10px;padding:2px 14px 8px;flex-wrap:wrap">
  {#each defs as [k, label, n]}
    <button onclick={() => pick(k)} style="flex:1 1 150px;min-width:130px;text-align:left;cursor:pointer;
      border-radius:11px;padding:11px 13px;box-shadow:var(--sh);
      background:{store.patrolFilter === k ? 'var(--infobg)' : 'var(--row)'};
      border:1px solid {store.patrolFilter === k ? 'var(--info)' : 'var(--bd2)'}">
      <div class="mono" style="font-size:22px;font-weight:700;color:var(--t1)">{n}</div>
      <div style="font:500 11px var(--f-sans);color:var(--t3);margin-top:2px">{label}</div>
    </button>
  {/each}
</div>
