<script>
  import {
    prefs, ui, eff, toggleCol, setReveal, postModel,
    closeSettings, saveSettings, discardSettings, keepEditing, resetSettings, settingsDirty
  } from './state.svelte.js';
  import { feed } from './data.svelte.js';
  import { fmtK } from './fmt.js';
  import Stepper from './Stepper.svelte';
  import DualRange from './DualRange.svelte';

  const dirty = $derived(settingsDirty());
  const densityLabel = $derived({ patrol: '巡检', standard: '标准', debug: '排查' }[prefs.density]);

  // window 来源标签（手动 override / 实测证据 / 探测候选 / 未知死角）——纯展示
  const SRC = {
    manual:    { label: '手动',  cls: 'text-info' },
    evidence:  { label: '实测',  cls: 'text-ok' },
    candidate: { label: '候选',  cls: 'text-warn' },
    unknown:   { label: '?',     cls: 'text-t4' }
  };
  // 每-model 服务端配置：即时 POST，SSE 回流刷新（不进本机 prefs 快照）。空 window = 清除 override。
  function commitWindow(model, raw) {
    const s = (raw || '').trim();
    if (s === '') { postModel(model, { window: null }); return; }   // 清除 → 回落证据链
    const n = Math.round(Number(s));
    if (Number.isFinite(n) && n > 0) postModel(model, { window: n });
  }
  const REDACT = '[redacted]';
  const aliasMasked = (a) => a === REDACT;             // server-redacted (reveal off) → don't edit
  function commitAlias(model, raw) {
    if (raw === REDACT) return;                         // never write the mask back as the alias
    postModel(model, { alias: (raw || '').trim() });
  }
  const onEnter = (fn) => (e) => { if (e.key === 'Enter') { e.preventDefault(); fn(e); e.currentTarget.blur(); } };

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
    class="flex max-h-[88vh] w-full max-w-[440px] flex-col rounded-[14px] border border-bd bg-panel"
    role="dialog" tabindex="-1"
    onclick={(e) => e.stopPropagation()}
    onkeydown={(e) => e.stopPropagation()}
  >
    <div class="flex items-center px-5 pb-3 pt-[18px]">
      <div class="text-[14px] font-semibold text-t1">设置</div>
      <div class="flex-1"></div>
      <button class="flex size-[30px] cursor-pointer items-center justify-center rounded-lg border border-bd2 font-mono text-[13px] text-t3" onclick={closeSettings} aria-label="关闭">✕</button>
    </div>

    <div class="cc-scroll min-h-0 flex-1 overflow-auto px-5 pb-1">
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

    <!-- 字体 -->
    <div class="mb-2 mt-[18px] font-mono text-[10.5px] font-semibold tracking-[.08em] text-t4">字体</div>
    <button
      class="w-full cursor-pointer rounded-[10px] border bg-chip px-3.5 py-3 text-left {prefs.webFonts ? 'border-info' : 'border-bd2'}"
      onclick={() => (prefs.webFonts = !prefs.webFonts)}
    >
      <div class="flex items-center gap-2.5">
        <div class="flex-1">
          <div class="text-[12.5px] font-medium text-t1">加载设计 Web 字体</div>
          <div class="mt-0.5 text-[11px] leading-[1.6] text-t4">Noto Sans SC / JetBrains Mono（首次需联网拉取）· 关 = 系统字体（离线、无外部请求）</div>
        </div>
        <div class="flex h-[22px] w-[38px] shrink-0 rounded-[11px] p-0.5 {prefs.webFonts ? 'justify-end bg-info' : 'justify-start bg-chip2'}">
          <div class="size-[18px] rounded-full bg-panel shadow"></div>
        </div>
      </div>
    </button>

    <!-- 列自定义（US4） -->
    <div class="mb-2 mt-[18px] flex items-baseline gap-2">
      <span class="font-mono text-[10.5px] font-semibold tracking-[.08em] text-t4">列自定义</span>
      <span class="text-[10.5px] text-t4">当前预设：{densityLabel}{prefs.colsOverride ? ' · 已修改' : ''}</span>
    </div>
    <div class="flex flex-wrap gap-1.5">
      <span class="rounded-full border border-bd2 bg-chip px-[11px] py-1 font-mono text-[11px] font-medium text-t4">status 🔒</span>
      <span class="rounded-full border border-bd2 bg-chip px-[11px] py-1 font-mono text-[11px] font-medium text-t4">名字 🔒</span>
      {#each [['prompt', 'prompt'], ['ctx', 'context'], ['model', '模型'], ['idle', 'idle']] as [key, label] (key)}
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
      <div class="border-t border-bd2 px-3.5 pb-[13px] pt-[11px]">
        <div class="text-[12px] font-medium text-t1">context 阈值</div>
        <div class="mb-1 mt-0.5 text-[10.5px] leading-normal text-t4">关注 → 条变琥珀（巡检列入「需关注」）· 危险 → 条变红、百分比加粗</div>
        <DualRange
          warn={eff.warn} danger={eff.danger}
          setWarn={(v) => (prefs.ctxWarn = Math.min(Math.max(0, v), eff.danger))}
          setDanger={(v) => (prefs.ctxDanger = Math.max(Math.min(100, v), eff.warn))}
        />
      </div>
    </div>

    <!-- 模型 / 窗口容量（per-model 服务端配置：alias + 手动 override + 探测候选采纳） -->
    <div class="mb-2 mt-[18px] flex items-baseline gap-2">
      <span class="font-mono text-[10.5px] font-semibold tracking-[.08em] text-t4">模型 / 窗口容量</span>
      <span class="text-[10.5px] text-t4">手动 override 覆盖自动探测 · 空=回落实测</span>
    </div>
    {#if feed.models.length === 0}
      <div class="rounded-[10px] border border-bd2 bg-chip px-3.5 py-3 text-[11px] text-t4">当前无在册会话可归类模型</div>
    {:else}
      <div class="rounded-[10px] border border-bd2 bg-chip">
        {#each feed.models as m, i (m.model)}
          <div class="px-3.5 py-3 {i > 0 ? 'border-t border-bd2' : ''}">
            <div class="flex items-baseline gap-2">
              <span class="min-w-0 flex-1 truncate font-mono text-[12px] font-medium text-t1">{aliasMasked(m.alias) ? m.model : (m.alias || m.model)}</span>
              <span class="shrink-0 text-[11px] tabular-nums {(SRC[m.win_source] || SRC.unknown).cls}">
                {fmtK(m.win || 0)} · {(SRC[m.win_source] || SRC.unknown).label}
              </span>
            </div>
            {#if m.alias && !aliasMasked(m.alias)}<div class="mt-0.5 font-mono text-[10px] text-t4">{m.model}</div>{/if}
            <div class="mt-0.5 text-[10px] text-t4">{m.sessions} 个在册会话{aliasMasked(m.alias) ? ' · 别名已隐藏' : ''}</div>

            <div class="mt-2 flex gap-2">
              <input
                class="min-w-0 flex-1 rounded-[7px] border border-bd2 bg-well px-2.5 py-1.5 text-[11.5px] text-t1 outline-none focus:border-info disabled:opacity-50"
                placeholder={aliasMasked(m.alias) ? '别名已隐藏 · 开启「下发原文」编辑' : '别名（可选）'}
                value={aliasMasked(m.alias) ? '' : (m.alias || '')}
                disabled={aliasMasked(m.alias)}
                onkeydown={onEnter((e) => commitAlias(m.model, e.currentTarget.value))}
                onblur={(e) => commitAlias(m.model, e.currentTarget.value)}
              />
              <input
                class="w-[120px] shrink-0 rounded-[7px] border border-bd2 bg-well px-2.5 py-1.5 text-[11.5px] tabular-nums text-t1 outline-none focus:border-info"
                inputmode="numeric"
                placeholder="窗口 override"
                value={m.override ?? ''}
                onkeydown={onEnter((e) => commitWindow(m.model, e.currentTarget.value))}
                onblur={(e) => commitWindow(m.model, e.currentTarget.value)}
              />
            </div>

            {#if m.candidate && !m.override}
              <div class="mt-2 flex items-center gap-2 rounded-[7px] border border-warn bg-warnbg px-2.5 py-1.5">
                <span class="flex-1 text-[10.5px] leading-[1.5] text-t3">探测到窗口 <span class="font-medium tabular-nums text-t1">{fmtK(m.candidate)}</span>{m.win_source === 'candidate' ? '（已用于填补 ? 死角）' : ''}</span>
                <button
                  class="shrink-0 cursor-pointer rounded-[6px] bg-info px-2.5 py-1 text-[11px] font-medium text-panel"
                  onclick={() => postModel(m.model, { window: m.candidate })}
                >采纳</button>
              </div>
            {/if}
          </div>
        {/each}
      </div>
      <div class="mx-0.5 mt-[7px] text-[10.5px] leading-[1.7] text-t4">改动即时生效（服务端持久化，非本机偏好）· 「采纳」= 把探测值提升为手动 override</div>
    {/if}

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
    </div><!-- /scroll -->

    <!-- save / reset（浮动固定底部） -->
    <div class="flex items-center gap-2.5 rounded-b-[14px] border-t border-bd2 bg-panel px-5 py-3.5">
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
