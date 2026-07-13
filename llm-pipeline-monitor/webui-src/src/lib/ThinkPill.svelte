<script>
  // thinking level 徽标（pill）：显示 effort 值本身，无「推理」前缀文字（前缀进 tooltip）
  let { effort = null } = $props();
</script>
{#if effort}
  <span
    class="shrink-0 rounded-full bg-chip2 px-1.5 py-px font-mono text-[9.5px] font-semibold uppercase tracking-wide text-t2"
    title="推理强度 {effort}"
  >{effort}</span>
{/if}
