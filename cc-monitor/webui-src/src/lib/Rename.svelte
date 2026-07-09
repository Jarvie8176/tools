<script>
  import { ui, commitRename, cancelRename, startRename } from './state.svelte.js';
  let { r } = $props();

  function onkeydown(e) {
    if (e.key === 'Enter') commitRename();
    if (e.key === 'Escape') cancelRename();
  }
</script>

{#if r.renaming}
  <div class="flex items-center gap-2">
    <!-- svelte-ignore a11y_autofocus -->
    <input
      class="min-w-0 flex-1 rounded-[7px] border border-info bg-well px-[11px] py-2 text-[12.5px] text-t1 outline-none"
      placeholder="给这个 session 起个名字…"
      bind:value={ui.renameVal}
      {onkeydown}
      autofocus
    />
    <button class="cursor-pointer rounded-[7px] bg-info px-[15px] py-2 text-[12px] font-medium text-panel" onclick={commitRename}>保存</button>
    <button class="cursor-pointer px-3 py-2 text-[12px] font-medium text-t3" onclick={cancelRename}>取消</button>
  </div>
{:else if !r.orphan}
  <div class="flex gap-2.5">
    <button
      class="cursor-pointer rounded-[7px] border border-info px-3.5 py-1.5 text-[12px] font-medium text-info"
      onclick={(e) => { e.stopPropagation(); startRename(r.id, r.rawName); }}
    >✎ 重命名</button>
  </div>
{/if}
