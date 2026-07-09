<script lang="ts">
  import type { Session } from "../types";
  import { titleOf } from "../format";
  import RedactText from "./RedactText.svelte";
  let { r }: { r: Session } = $props();
  let ti = $derived(titleOf(r));
</script>
{#if ti.t}
  <span style="font:500 13.5px var(--f-sans);color:var(--t1)"><RedactText text={ti.t} /></span>
{:else if r.name && r.name !== "-"}
  <span class="mono" style="font-size:12.5px;color:var(--t1)">{r.name}</span>
{:else}
  <span class="mono" style="font-size:12.5px;color:var(--t4)">{r.u8 || "—"}</span>
{/if}
