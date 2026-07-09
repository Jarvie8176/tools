<script>
  // per-session 模型 chip（cards/feed 用）：显示 模型 + think level（effort）
  let { model, effort = null } = $props();
</script>
{#if model && model !== '—'}
  <span
    class="shrink-0 rounded-[4px] border border-bd2 bg-chip px-1.5 py-px font-mono text-[10px] font-medium text-t3"
    title="模型 {model}{effort ? ` · 推理 ${effort}` : ''}"
  >{model}{#if effort}<span class="text-t4"> · {effort}</span>{/if}</span>
{/if}
