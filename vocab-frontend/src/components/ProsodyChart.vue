<script setup lang="ts">
import { computed, ref } from 'vue'
import type { Measurement } from '@/api/pronunciation'

const props = defineProps<{
  result: Measurement
  comparison?: Measurement
  comparisonLabel?: string
}>()
const emit = defineEmits<{ (event: 'seek', time: number): void }>()
const mode = ref<'pitch' | 'energy'>('pitch')
const reference = computed(() => props.comparison || props.result.reference?.result)
const series = (data: Measurement) =>
  mode.value === 'pitch' ? data.chart.semitones : data.chart.energy_dbfs
const bounds = computed(() => {
  const values = [
    ...series(props.result),
    ...(reference.value ? series(reference.value) : [])
  ].filter((v): v is number => v !== null && Number.isFinite(v))
  return mode.value === 'pitch'
    ? [Math.min(-6, ...values) - 1, Math.max(6, ...values) + 1]
    : [Math.min(-60, ...values) - 3, Math.max(-10, ...values) + 3]
})
function path(data: Measurement) {
  const values = series(data)
  let open = false
  return values
    .map((v, i) => {
      if (v === null) {
        open = false
        return ''
      }
      const x =
        58 +
        (800 * (data.chart.time_s[i] - data.selection.start_s)) /
          (data.selection.end_s - data.selection.start_s)
      const y = 210 - (170 * (v - bounds.value[0])) / (bounds.value[1] - bounds.value[0])
      const command = open ? 'L' : 'M'
      open = true
      return `${command}${x.toFixed(2)},${y.toFixed(2)}`
    })
    .join(' ')
}
const ticks = computed(() =>
  [0, 0.25, 0.5, 0.75, 1].map((p) => ({
    y: 210 - 170 * p,
    label: (bounds.value[0] + p * (bounds.value[1] - bounds.value[0])).toFixed(0)
  }))
)
const waveformPath = computed(() =>
  props.result.chart.waveform
    .map(([time, low, high]) => {
      const x = 58 + (800 * time) / props.result.duration_s
      return `M${x.toFixed(1)},${(45 + low * 36).toFixed(1)}L${x.toFixed(1)},${(45 + high * 36).toFixed(1)}`
    })
    .join(' ')
)
</script>

<template>
  <section class="chart-box">
    <div class="chart-heading">
      <h3>听见之外，也看见变化</h3>
      <div class="chart-switch" aria-label="图表类型">
        <button :aria-pressed="mode === 'pitch'" @click="mode = 'pitch'">相对音高</button
        ><button :aria-pressed="mode === 'energy'" @click="mode = 'energy'">相对音量</button>
      </div>
    </div>
    <div class="legend">
      <span class="own">你的录音</span
      ><span v-if="reference" class="reference">{{
        comparisonLabel || result.reference?.label || '对比录音'
      }}</span>
    </div>
    <svg
      viewBox="0 0 900 250"
      role="img"
      :aria-label="
        mode === 'pitch'
          ? '本人和参照的相对音高曲线，单位半音'
          : '本人和参照的数字音量曲线，单位 dBFS'
      "
    >
      <g v-for="tick in ticks" :key="tick.y">
        <line x1="58" x2="858" :y1="tick.y" :y2="tick.y" class="grid" />
        <text x="47" :y="tick.y + 4" text-anchor="end">{{ tick.label }}</text>
      </g>
      <text x="15" y="20">{{ mode === 'pitch' ? '半音' : 'dBFS' }}</text>
      <path v-if="reference" :d="path(reference)" class="reference-line" />
      <path :d="path(result)" class="own-line" />
      <g v-for="(p, i) in [0, 0.25, 0.5, 0.75, 1]" :key="i">
        <text :x="58 + 800 * p" y="235" text-anchor="middle">{{ p * 100 }}%</text>
      </g>
    </svg>
    <p class="chart-note">
      横轴按选区归一化以比较走势；实际时长单独保留。清辅音的音高空缺保持断开。
    </p>
    <div class="word-timeline" aria-label="词语定位">
      <button v-for="(word, i) in result.words" :key="i" @click="emit('seek', word.start_s)">
        {{ word.text }}<small>{{ word.start_s.toFixed(2) }}s</small>
      </button>
    </div>
    <svg class="waveform" viewBox="0 0 900 100" role="img" aria-label="录音实际时间与振幅波形">
      <line x1="58" x2="858" y1="45" y2="45" class="grid" />
      <path :d="waveformPath" stroke="#7694bd" stroke-width="1.5" fill="none" />
      <text x="58" y="92">0s</text>
      <text x="858" y="92" text-anchor="end">{{ result.duration_s.toFixed(2) }}s</text>
      <text x="15" y="20">振幅</text>
    </svg>
  </section>
</template>

<style scoped>
.chart-box {
  border: 1px solid var(--cet-line);
  border-radius: 18px;
  padding: 24px;
  background: var(--cet-surface);
}
.chart-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}
h3 {
  font-size: 17px;
  margin: 0;
}
.chart-switch {
  display: flex;
  gap: 4px;
  background: var(--cet-surface-2);
  padding: 4px;
  border-radius: 9px;
}
button {
  font: inherit;
  cursor: pointer;
  color: var(--cet-text);
  background: transparent;
  border: 0;
  padding: 7px 12px;
  border-radius: 7px;
}
.chart-switch button[aria-pressed='true'] {
  background: var(--cet-surface);
  box-shadow: 0 1px 5px #0001;
}
.legend {
  display: flex;
  gap: 24px;
  font-size: 12px;
  margin: 20px 0 0;
  color: var(--cet-muted);
}
.legend span:before {
  content: '';
  display: inline-block;
  width: 17px;
  height: 3px;
  margin: 0 7px 3px 0;
  background: #2563eb;
}
.legend .reference:before {
  background: #e69548;
}
svg {
  display: block;
  width: 100%;
  overflow: visible;
  margin-top: 12px;
}
text {
  font: 12px system-ui;
  fill: var(--cet-muted);
}
.grid {
  stroke: var(--cet-line);
  stroke-dasharray: 4 4;
}
.own-line,
.reference-line {
  fill: none;
  stroke: #2563eb;
  stroke-width: 2;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.reference-line {
  stroke: #e69548;
  stroke-width: 1.8;
  stroke-dasharray: 6 3;
}
.chart-note {
  font-size: 12px;
  color: var(--cet-muted);
  line-height: 1.8;
}
.word-timeline {
  display: flex;
  gap: 7px;
  flex-wrap: wrap;
  padding-top: 14px;
  border-top: 1px solid var(--cet-line);
}
.word-timeline button {
  background: var(--cet-surface-2);
  text-align: left;
}
.word-timeline button:hover {
  background: var(--cet-brand-tint);
}
small {
  display: block;
  font-size: 10px;
  color: var(--cet-muted);
  margin-top: 4px;
}
@media (max-width: 600px) {
  .chart-box {
    padding: 16px;
  }
  .chart-heading h3 {
    font-size: 15px;
  }
  .legend {
    gap: 12px;
    flex-wrap: wrap;
  }
}
</style>
