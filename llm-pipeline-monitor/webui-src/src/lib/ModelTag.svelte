<script>
  // cards/feed 用：模型 chip + thinking level pill
  import ThinkPill from './ThinkPill.svelte';
  let { model, effort = null } = $props();
</script>
{#if model && model !== '—'}
  <span class="inline-flex shrink-0 items-center gap-1">
    <span
      class="rounded-[4px] border border-bd2 bg-chip px-1.5 py-px font-mono text-[10px] font-medium text-t3"
      title="模型 {model}"
    >{model}</span>
    <ThinkPill effort={effort} />
  </span>
{/if}
