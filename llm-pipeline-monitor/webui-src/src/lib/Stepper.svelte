<script>
  let { value, valueCls = 'text-t1', dec, inc } = $props();
</script>

<div class="flex shrink-0 items-center rounded-lg border border-bd2">
  <button class="flex size-[30px] cursor-pointer items-center justify-center font-mono text-[14px] font-medium text-t3" onclick={dec}>−</button>
  <div class="min-w-10 text-center font-mono text-[12px] font-semibold {valueCls}">{value}</div>
  <button class="flex size-[30px] cursor-pointer items-center justify-center font-mono text-[14px] font-medium text-t3" onclick={inc}>+</button>
</div>
