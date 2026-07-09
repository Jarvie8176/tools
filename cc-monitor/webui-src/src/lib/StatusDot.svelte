<script>
  let { status, label = false } = $props();
</script>

{#if status === 'orphaned'}
  <span class="font-mono text-[12px] font-semibold text-warn shrink-0">▲</span>
{:else if status === 'busy'}
  <span class="ccpulse-fast size-2 shrink-0 rounded-full bg-ok"></span>
{:else}
  <span class="size-2 shrink-0 rounded-full border-2 border-info box-border"></span>
{/if}
{#if label}
  <span class="font-mono text-[11px] font-semibold {status === 'busy' ? 'text-ok' : status === 'orphaned' ? 'text-warn' : 'text-info'}">{status}</span>
{/if}
