<script lang="ts">
  import type { Session } from "../types";
  import { store } from "../store.svelte";
  import { fmtIdle, nowS } from "../format";
  let { r }: { r: Session } = $props();
  // store.tick bumps every second → this re-derives without a server push (no wall-clock in payload)
  let label = $derived((store.tick, r.last_activity_ts ? fmtIdle(nowS() - r.last_activity_ts) : "—"));
</script>
<span class="mono" style="font-size:12px;color:var(--t3);white-space:nowrap">{label}</span>
