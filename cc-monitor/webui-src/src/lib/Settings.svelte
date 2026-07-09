<script>
  import {
    prefs, ui, eff, toggleCol, setReveal,
    closeSettings, saveSettings, discardSettings, keepEditing, resetSettings, settingsDirty
  } from './state.svelte.js';
  import Stepper from './Stepper.svelte';

  const dirty = $derived(settingsDirty());
  const densityLabel = $derived({ patrol: '巡检', standard: '标准', debug: '排查' }[prefs.density]);

  const LEGEND = [
    { icon: 'busy', term: 'busy', cls: 'text-ok', desc: '生成中，正在产出' },
    { icon: 'active', term: 'active', cls: 'text-info', desc: '已注册、可达，等待输入' },
    { icon: 'orphaned', term: 'orphaned', cls: 'text-warn', desc: '.url 台账残留，不可达' },
    { icon: 'live', term: '实时', cls: 'text-ok', sans: true, desc: '推送通道（SSE 单流）已连接，更新即时到达，非轮询；断开时 badge 变为「已断开 · 重连中」' },
    { icon: null, term: '来源核对', cls: 'text-t3', sans: true, desc: 'header 下的计数条：registry / managed / env-spawned / .url 台账各自记录的 session 数互相核对，对不上时琥珀高亮（如 .url 多 1 条 = 有残留待清理）' },
    { icon: null, term: 'idle', cls: 'text-t3', desc: '本地 tick 计时，payload 无 wall-clock 字段' },
    { icon: null, term: '/legacy', cls: 'text-t3', desc: '零 JS fallback，任何浏览器可用' }
  ];
</script>

<div
  class="fixed inset-0 z-[60] flex items-center justify-center bg-black/55 p-4"
  role="button" tabindex="-1"
  onclick={closeSettings}
  onkeydown={(e) => e.key === 'Escape' && closeSettings()}
>
  <div
    class="max-h-[88vh] w-full max-w-[440px] overflow-auto rounded-[14px] border border-bd bg-panel px-5 pb-5 pt-[18px]"
    role="dialog" tabindex="-1"
    onclick={(e) => e.stopPropagation()}
    onkeydown={(e) => e.stopPropagation()}
  >
    <div class="mb-4 flex items-center">
      <div class="text-[14px] font-semibold text-t1">设置</div>
      <div class="flex-1"></div>
      <button class="flex size-[30px] cursor-pointer items-center justify-center rounded-lg border border-bd2 font-mono text-[13px] text-t3" onclick={closeSettings} aria-label="关闭">✕</button>
    </div>

    {#if ui.confirmClose}
      <div class="mb-3.5 rounded-[10px] border border-warn bg-warnbg px-3.5 py-3">
        <div class="text-[12.5px] font-medium text-t1">有未保存的修改</div>
        <div class="mt-2.5 flex gap-2">
          <button class="cursor-pointer rounded-[7px] bg-info px-3.5 py-[7px] text-[12px] font-medium text-panel" onclick={saveSettings}>保存并关闭</button>
          <button class="cursor-pointer rounded-[7px] border border-bd2 px-3.5 py-[7px] text-[12px] font-medium text-t3" onclick={discardSettings}>放弃修改</button>
          <div class="flex-1"></div>
          <button class="cursor-pointer px-2.5 py-[7px] text-[12px] font-medium text-t3" onclick={keepEditing}>继续编辑</button>
        </div>
      </div>
    {/if}

    <!-- 隐私（US5 / D3：单用户，无设备认证） -->
    <div class="mb-2 font-mono text-[10.5px] font-semibold tracking-[.08em] text-t4">隐私</div>
    <button
      class="w-full cursor-pointer rounded-[10px] border bg-chip px-3.5 py-3 text-left {prefs.reveal ? 'border-info' : 'border-bd2'}"
      onclick={() => setReveal(!prefs.reveal)}
    >
      <div class="flex items-center gap-2.5">
        <div class="flex-1">
          <div class="text-[12.5px] font-medium text-t1">下发 prompt / title 原文</div>
          <div class="mt-0.5 text-[11px] leading-[1.6] text-t4">关 = 服务端脱敏后下发（投屏/截图安全）· 开 = 下发原文，header 挂「原文」badge</div>
        </div>
        <div class="flex h-[22px] w-[38px] shrink-0 rounded-[11px] p-0.5 {prefs.reveal ? 'justify-end bg-info' : 'justify-start bg-chip2'}">
          <div class="size-[18px] rounded-full bg-panel shadow"></div>
        </div>
      </div>
    </button>
    <div class="mx-0.5 mt-[7px] text-[10.5px] leading-[1.7] text-t4">开关即生效（下一次 payload 起）· 单用户，无设备认证 · 偏好仅存本浏览器</div>

    <!-- 主题 -->
    <div class="mb-2 mt-[18px] font-mono text-[10.5px] font-semibold tracking-[.08em] text-t4">主题</div>
    <div class="flex gap-[3px] rounded-lg border border-bd2 bg-chip p-[3px]">
      {#each [['dark', '暗色'], ['light', '亮色']] as [key, label] (key)}
        <button
          class="flex-1 cursor-pointer rounded-md py-[7px] text-center text-[12px] font-medium {prefs.theme === key ? 'bg-chip2 text-t1' : 'text-t3'}"
          onclick={() => (prefs.theme = key)}
        >{label}</button>
      {/each}
    </div>

    <!-- 列自定义（US4） -->
    <div class="mb-2 mt-[18px] flex items-baseline gap-2">
      <span class="font-mono text-[10.5px] font-semibold tracking-[.08em] text-t4">列自定义</span>
      <span class="text-[10.5px] text-t4">当前预设：{densityLabel}{prefs.colsOverride ? ' · 已修改' : ''}</span>
    </div>
    <div class="flex flex-wrap gap-1.5">
      <span class="rounded-full border border-bd2 bg-chip px-[11px] py-1 font-mono text-[11px] font-medium text-t4">status 🔒</span>
      <span class="rounded-full border border-bd2 bg-chip px-[11px] py-1 font-mono text-[11px] font-medium text-t4">名字 🔒</span>
      {#each [['prompt', 'prompt'], ['ctx', 'context'], ['idle', 'idle']] as [key, label] (key)}
        <button
          class="cursor-pointer rounded-full border px-[11px] py-1 font-mono text-[11px] font-medium
                 {eff.cols[key] ? 'border-info bg-infobg text-info' : 'border-bd2 text-t3'}"
          onclick={() => toggleCol(key)}
        >{label} {eff.cols[key] ? '✓' : ''}</button>
      {/each}
    </div>
    <div class="mx-0.5 mt-[7px] text-[10.5px] leading-[1.7] text-t4">切换预设会重置自定义 · 次要字段（会话/bridge ID、模型、累计 tokens、窗口）固定在展开详情里</div>

    <!-- 显示 -->
    <div class="mb-2 mt-[18px] font-mono text-[10.5px] font-semibold tracking-[.08em] text-t4">显示</div>
    <div class="rounded-[10px] border border-bd2 bg-chip">
      <div class="flex items-center gap-2.5 px-3.5 py-[11px]">
        <div class="min-w-0 flex-1">
          <div class="text-[12px] font-medium text-t1">prompt 摘要行数</div>
          <div class="mt-0.5 text-[10.5px] leading-normal text-t4">列表里按视觉行截断，CJK 按实际字宽</div>
        </div>
        <Stepper value={String(eff.lines)} dec={() => (prefs.promptLines = Math.max(1, eff.lines - 1))} inc={() => (prefs.promptLines = Math.min(4, eff.lines + 1))} />
      </div>
      <div class="flex items-center gap-2.5 border-t border-bd2 px-3.5 py-[11px]">
        <div class="min-w-0 flex-1">
          <div class="text-[12px] font-medium text-t1">context 关注阈值</div>
          <div class="mt-0.5 text-[10.5px] leading-normal text-t4">达到后条变琥珀，巡检里列入「需关注」</div>
        </div>
        <Stepper value={eff.warn + '%'} valueCls="text-warn" dec={() => (prefs.ctxWarn = Math.max(10, eff.warn - 5))} inc={() => (prefs.ctxWarn = Math.min(eff.danger - 5, eff.warn + 5))} />
      </div>
      <div class="flex items-center gap-2.5 border-t border-bd2 px-3.5 py-[11px]">
        <div class="min-w-0 flex-1">
          <div class="text-[12px] font-medium text-t1">context 危险阈值</div>
          <div class="mt-0.5 text-[10.5px] leading-normal text-t4">条变红、百分比加粗</div>
        </div>
        <Stepper value={eff.danger + '%'} valueCls="text-dgr" dec={() => (prefs.ctxDanger = Math.max(eff.warn + 5, eff.danger - 5))} inc={() => (prefs.ctxDanger = Math.min(95, eff.danger + 5))} />
      </div>
    </div>

    <!-- 图例 -->
    <div class="mb-2 mt-[18px] font-mono text-[10.5px] font-semibold tracking-[.08em] text-t4">图例</div>
    <div class="rounded-[10px] border border-bd2 bg-chip">
      {#each LEGEND as l, i (l.term)}
        <div class="flex items-start gap-2.5 px-3.5 py-2.5 {i > 0 ? 'border-t border-bd2' : ''}">
          <span class="mt-1 flex w-2 shrink-0 justify-center">
            {#if l.icon === 'busy'}<span class="ccpulse-fast size-2 rounded-full bg-ok"></span>
            {:else if l.icon === 'active'}<span class="size-2 rounded-full border-2 border-info box-border"></span>
            {:else if l.icon === 'orphaned'}<span class="font-mono text-[11px] font-semibold leading-none text-warn">▲</span>
            {:else if l.icon === 'live'}<span class="ccpulse size-2 rounded-full bg-ok"></span>
            {/if}
          </span>
          <span class="w-[62px] shrink-0 text-[11px] font-semibold {l.cls} {l.sans ? '' : 'font-mono'}">{l.term}</span>
          <span class="text-[11.5px] leading-[1.6] text-t3">{l.desc}</span>
        </div>
      {/each}
    </div>

    <!-- save / reset -->
    <div class="mt-5 flex items-center gap-2.5 border-t border-bd2 pt-3.5">
      <button class="cursor-pointer rounded-[7px] border border-bd2 px-3.5 py-2 text-[12px] font-medium text-t3" onclick={resetSettings}>恢复默认</button>
      <div class="flex-1"></div>
      {#if dirty}<span class="text-[10.5px] text-warn">未保存</span>{/if}
      <button
        class="cursor-pointer rounded-[7px] px-5 py-2 text-[12px] font-medium {dirty ? 'bg-info text-panel' : 'bg-chip2 text-t3'}"
        onclick={saveSettings}
      >保存</button>
    </div>
  </div>
</div>
