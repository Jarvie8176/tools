<script lang="ts">
  import { store } from "../store.svelte";
  let { open = $bindable() }: { open: boolean } = $props();
  const p = () => store.prefs;
  function save() { store.savePrefs(); }
  function setWarn(v: number) { store.prefs.ctxWarn = Math.min(Math.max(0, v || 0), store.prefs.ctxDanger); save(); }
  function setDanger(v: number) { store.prefs.ctxDanger = Math.max(Math.min(100, v || 0), store.prefs.ctxWarn); save(); }
  function reset() {
    store.prefs = { density: p().density, theme: "dark", promptLines: 2, ctxWarn: 50, ctxDanger: 80,
      cols: { prompt: true, ctx: true, idle: true } };
    save();
  }
</script>

<div class="backdrop" class:show={open} onclick={() => (open = false)} role="presentation"></div>
<aside class="drawer" class:show={open}>
  <div style="display:flex;align-items:center;justify-content:space-between">
    <b style="font:500 13.5px var(--f-sans);color:var(--t1)">设置</b>
    <button class="ico" onclick={() => (open = false)}>✕</button>
  </div>

  <div class="grp"><h3>隐私</h3>
    <div class="row"><label for="rv">显示原文 prompt / title</label>
      <input id="rv" type="checkbox" checked={store.revealOn} onchange={(e) => store.setReveal(e.currentTarget.checked)} /></div>
    <div class="lg">关闭 = 服务端脱敏（▓ 块）· 打开 = 服务端下发原文（header 常驻「原文」badge）。单用户，无设备认证。</div>
  </div>

  <div class="grp"><h3>外观</h3>
    <div class="row"><label for="th">亮色主题</label>
      <input id="th" type="checkbox" checked={p().theme === "light"} onchange={(e) => { store.prefs.theme = e.currentTarget.checked ? 'light' : 'dark'; save(); }} /></div>
    <div class="row"><label for="ln">prompt 摘要行数</label>
      <span style="display:flex;align-items:center;gap:8px">
        <input id="ln" type="range" min="1" max="4" step="1" value={p().promptLines}
          oninput={(e) => { store.prefs.promptLines = +e.currentTarget.value; save(); }} style="width:110px" />
        <b class="mono" style="color:var(--t1);min-width:34px;text-align:right">{p().promptLines} 行</b>
      </span></div>
  </div>

  <div class="grp"><h3>context 阈值 (%)</h3>
    <div class="dual" style="position:relative;height:26px;margin:10px 2px 4px">
      <div style="position:absolute;top:10px;left:0;right:0;height:6px;background:var(--ok);border-radius:3px"></div>
      <div style="position:absolute;top:10px;height:6px;background:var(--warn);left:{p().ctxWarn}%;width:{Math.max(0,p().ctxDanger-p().ctxWarn)}%"></div>
      <div style="position:absolute;top:10px;height:6px;background:var(--dgr);border-radius:0 3px 3px 0;left:{p().ctxDanger}%;width:{Math.max(0,100-p().ctxDanger)}%"></div>
      <input type="range" min="0" max="100" step="1" value={p().ctxWarn} oninput={(e) => setWarn(+e.currentTarget.value)} aria-label="关注阈值" />
      <input type="range" min="0" max="100" step="1" value={p().ctxDanger} oninput={(e) => setDanger(+e.currentTarget.value)} aria-label="危险阈值" />
    </div>
    <div class="lg"><span style="color:var(--warn)">关注</span> <b class="mono">{p().ctxWarn}</b>% 起 · <span style="color:var(--dgr)">危险</span> <b class="mono">{p().ctxDanger}</b>% 起（拖动两个滑块）</div>
  </div>

  <div class="grp"><h3>列（标准表格）</h3>
    {#each [["prompt", "最新 prompt"], ["ctx", "context"], ["idle", "idle"]] as [k, label]}
      <div class="row"><label for="col-{k}">{label}</label>
        <input id="col-{k}" type="checkbox" checked={p().cols[k as "prompt"|"ctx"|"idle"]}
          onchange={(e) => { store.prefs.cols[k as "prompt"|"ctx"|"idle"] = e.currentTarget.checked; save(); }} /></div>
    {/each}
  </div>

  <div class="grp"><h3>图例</h3>
    <div class="lg">
      <div><span class="dot busy" style="margin-right:8px"></span>busy — 生成中，正在产出</div>
      <div><span class="dot active" style="margin-right:8px"></span>active — 已注册、可达，等待输入</div>
      <div><span class="dot orphaned" style="margin-right:8px"></span>orphaned — 台账残留，不可达（不可重命名）</div>
      <div style="margin-top:6px">context：<span style="color:var(--ok)">正常</span> · <span style="color:var(--warn)">关注</span> · <span style="color:var(--dgr)">危险</span></div>
      <div style="margin-top:6px">origin：<b>mgd</b> managed · <b>env</b> rc-env-spawned · <b>cli</b> individual-cli · <b>·b</b> bridged</div>
      <div style="margin-top:6px">idle 由 last-activity 本地每秒推算（payload 无 wall-clock）。curl/无 JS 用 <span class="mono">/legacy</span>。</div>
    </div>
  </div>
  <div class="grp"><button class="ico" style="width:auto;padding:5px 11px" onclick={reset}>恢复默认</button></div>
</aside>

<style>
  .backdrop{position:fixed;inset:0;background:rgba(0,0,0,.5);display:none;z-index:20}
  .backdrop.show{display:block}
  .drawer{position:fixed;top:0;right:0;height:100%;width:min(380px,92vw);background:var(--panel);border-left:1px solid var(--bd);transform:translateX(100%);transition:transform .18s;z-index:21;overflow:auto;padding:16px}
  .drawer.show{transform:none}
  .grp{border-top:1px solid var(--bd2);padding:12px 0}
  .grp h3{font:600 12px var(--f-sans);color:var(--t1);margin:0 0 8px}
  .row{display:flex;align-items:center;justify-content:space-between;gap:10px;margin:6px 0;font-size:12.5px}
  .lg{font:400 11.5px var(--f-sans);color:var(--t3);line-height:1.7}
  .ico{background:none;border:1px solid var(--bd);color:var(--t2);border-radius:7px;height:30px;min-width:32px;cursor:pointer}
</style>
