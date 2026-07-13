<script>
  // 单轴双滑块：warn / danger 两 thumb 拖动，clamp warn ≤ danger，三段着色 + 数字读出。
  let { warn, danger, setWarn, setDanger } = $props();
</script>

<div class="dual">
  <div class="track"></div>
  <div class="seg" style="left:{warn}%;width:{Math.max(0, danger - warn)}%;background:var(--warn)"></div>
  <div class="seg" style="left:{danger}%;width:{Math.max(0, 100 - danger)}%;background:var(--dgr);border-radius:0 3px 3px 0"></div>
  <input type="range" min="0" max="100" step="1" value={warn}
    oninput={(e) => setWarn(+e.currentTarget.value)} aria-label="关注阈值" />
  <input type="range" min="0" max="100" step="1" value={danger}
    oninput={(e) => setDanger(+e.currentTarget.value)} aria-label="危险阈值" />
</div>
<div class="mt-1.5 flex items-center gap-1.5 text-[11px] font-medium">
  <span class="text-warn">关注 <span class="font-mono">{warn}</span>%</span>
  <span class="text-t4">·</span>
  <span class="text-dgr">危险 <span class="font-mono">{danger}</span>%</span>
  <span class="ml-auto text-[10.5px] text-t4">拖动两个滑块</span>
</div>
