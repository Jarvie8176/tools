<script lang="ts">
  import type { Session } from "../types";
  import { originAbbr } from "../format";
  let { r }: { r: Session } = $props();
</script>
{#if r.origin}
  <span class="mono" title="{r.origin}{r.bridged ? ' · cloud-bridged' : ''}"
    style="font-size:9.5px;font-weight:600;padding:1px 5px;border-radius:4px;background:var(--well);color:var(--t3);cursor:help">{originAbbr(r)}</span>
{/if}
