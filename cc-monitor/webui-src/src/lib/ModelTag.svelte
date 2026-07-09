<script>
  // per-session 模型小 chip（列表内紧凑显示；effort 进 tooltip）
  let { model, effort = null } = $props();
</script>
{#if model && model !== '—'}
  <span
    class="shrink-0 rounded-[4px] border border-bd2 bg-chip px-1.5 py-px font-mono text-[10px] font-medium text-t3"
    title={effort ? `模型 ${model} · 推理 ${effort}` : `模型 ${model}`}
  >{model}</span>
{/if}
