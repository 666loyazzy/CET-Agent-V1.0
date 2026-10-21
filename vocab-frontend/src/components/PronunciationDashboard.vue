<script setup lang="ts">
import { computed, ref } from 'vue'
import type { Measurement, Practice } from '@/api/pronunciation'

const props = defineProps<{
  result: Measurement
  practice: Practice
  history: Practice[]
  previous?: Measurement
  tip: string
}>()
const panel = ref('reference')
const panels = [
  ['reference', '参照对照'],
  ['dimensions', '多维表现'],
  ['energy', '音量节奏'],
  ['history', '复练轨迹']
]
const trendMetric = ref<'pitch_range_st' | 'contour_mae_st' | 'coverage_percent' | 'duration_s'>(
  'pitch_range_st'
)
const trendOptions = {
  pitch_range_st: ['音域跨度', '半音'],
  contour_mae_st: ['参照轮廓差', '半音'],
  coverage_percent: ['有效 F0 比例', '%'],
  duration_s: ['选区时长', '秒']
}
const evidence = computed(() => props.result.visuals)
const regions = computed(() => evidence.value?.regions || [])
const regionMax = computed(
  () => Math.max(1, ...regions.value.map((r) => r.median_f0_hz || 0)) * 1.2
)
const deviationMax = computed(
  () => Math.max(1, ...(evidence.value?.deviations || []).map((r) => r.value || 0)) * 1.2
)
const dimensions = computed(() => evidence.value?.dimensions || [])
const point = (i: number, ratio: number) => [
  200 + Math.sin((i * Math.PI) / 2) * 79 * ratio,
  125 - Math.cos((i * Math.PI) / 2) * 79 * ratio
]
const polygon = (ratio: number) => [0, 1, 2, 3].map((i) => point(i, ratio).join(',')).join(' ')
function radar(reference = false) {
  // Each axis has its own disclosed unit; an outer point is not a better pronunciation.
  return dimensions.value
    .map((d, i) =>
      point(
        i,
        Math.abs((reference ? d.reference : d.value) || 0) /
          Math.max(Math.abs(d.value || 0), Math.abs(d.reference || 0), 1)
      ).join(',')
    )
    .join(' ')
}
const radarReady = computed(() => dimensions.value.every((d) => d.value !== null))
const referenceReady = computed(
  () => props.result.reference && dimensions.value.every((d) => d.reference !== null)
)
const historyRows = computed(() =>
  props.history
    .filter(
      (p) =>
        p.status === 'completed' &&
        !p.is_reference &&
        p.observations?.comparison_key === props.result.comparison_key
    )
    .sort((a, b) => a.created_at - b.created_at)
)
const series = computed(() =>
  historyRows.value.map((p, i) => ({
    ...p,
    x: historyRows.value.length === 1 ? 320 : 55 + (530 * i) / (historyRows.value.length - 1),
    value: p.observations?.[trendMetric.value] ?? null
  }))
)
const trendMax = computed(() => Math.max(1, ...series.value.map((p) => p.value || 0)) * 1.15)
const y = (value: number) => 160 - (125 * value) / trendMax.value
const trendPath = computed(() => {
  let connected = false
  return series.value
    .map((p) => {
      if (p.value === null) {
        connected = false
        return ''
      }
      const command = connected ? 'L' : 'M'
      connected = true
      return `${command}${p.x},${y(p.value)}`
    })
    .join(' ')
})
const energyPath = computed(() =>
  props.result.chart.energy_dbfs
    .map((v, i) => {
      const s = props.result.selection
      return `${i ? 'L' : 'M'}${55 + (530 * (props.result.chart.time_s[i] - s.start_s)) / (s.end_s - s.start_s)},${160 - (125 * (Math.max(-80, v) + 80)) / 80}`
    })
    .join(' ')
)
const changes = computed(() => {
  const previous = props.previous
  if (!previous || previous.comparison_key !== props.result.comparison_key) return []
  return [
    {
      label: '选区时长变化',
      value:
        props.result.selection.end_s -
        props.result.selection.start_s -
        (previous.selection.end_s - previous.selection.start_s),
      unit: '秒'
    },
    {
      label: '音域跨度变化',
      value: props.result.features.pitch_range_st - previous.features.pitch_range_st,
      unit: '半音'
    },
    {
      label: '收尾音高差变化',
      value:
        props.result.features.ending_delta_st !== null && previous.features.ending_delta_st !== null
          ? props.result.features.ending_delta_st - previous.features.ending_delta_st
          : null,
      unit: '半音'
    }
  ]
})
const number = (value: number | null | undefined, places = 1) =>
  value == null ? '—' : value.toFixed(places)
const date = (timestamp: number) =>
  new Date(timestamp * 1000).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  })
</script>

<template>
  <section v-if="evidence" class="dashboard" aria-label="发音观测图解">
    <div class="dashboard-heading">
      <div>
        <span class="eyebrow">MEASURE · COMPARE · REPEAT</span>
        <h3>把每一遍的变化，看清楚</h3>
      </div>
      <span class="badge">真实声学数据</span>
    </div>
    <div class="hero">
      <div>
        <span>参照轮廓平均差</span
        ><strong>{{ number(evidence.contour_mae_st, 2) }} <small>半音</small></strong>
        <p>{{ evidence.paired_bins }} / 60 个时间格可比较</p>
      </div>
      <div>
        <span>本次观测</span>
        <p>中位音高 {{ number(result.features.median_f0_hz) }} Hz</p>
        <p>
          有效 F0 {{ evidence.coverage_percent }}% · 时长
          {{ (result.selection.end_s - result.selection.start_s).toFixed(2) }} 秒
        </p>
      </div>
    </div>
    <p class="caption">{{ evidence.comparison_note }}它不是英语发音总分或考试成绩。</p>
    <div class="viz-tabs" role="tablist" aria-label="发音分析图表">
      <button
        v-for="[id, label] in panels"
        :id="`viz-tab-${id}`"
        :key="id"
        role="tab"
        :aria-selected="panel === id"
        :aria-controls="`viz-${id}`"
        @click="panel = id"
      >
        {{ label }}
      </button>
    </div>
    <div
      v-if="panel === 'reference'"
      id="viz-reference"
      role="tabpanel"
      aria-labelledby="viz-tab-reference"
    >
      <div class="science-figures">
        <figure>
          <figcaption>有效基频比例</figcaption>
          <svg viewBox="0 0 200 175" role="img" aria-label="有效基频比例环图">
            <circle cx="100" cy="72" r="47" class="donut-base" />
            <circle
              cx="100"
              cy="72"
              r="47"
              class="donut-value"
              :stroke-dasharray="`${(295.31 * evidence.coverage_percent) / 100} 295.31`"
              transform="rotate(-90 100 72)"
            />
            <text x="100" y="78" class="large" text-anchor="middle">
              {{ evidence.coverage_percent }}%
            </text>
            <text x="100" y="150" text-anchor="middle">
              {{ result.quality.valid_frames }} / {{ result.quality.total_frames }} 帧
            </text>
          </svg>
        </figure>
        <figure>
          <figcaption>前、中、后段音高</figcaption>
          <svg viewBox="0 0 350 175" role="img" aria-label="前中后段中位音高柱图">
            <line x1="20" x2="335" y1="133" y2="133" class="grid" />
            <g v-for="(region, i) in regions" :key="region.label">
              <rect
                v-if="region.median_f0_hz !== null"
                :x="42 + i * 102"
                :y="133 - (100 * region.median_f0_hz) / regionMax"
                width="54"
                :height="(100 * region.median_f0_hz) / regionMax"
                rx="5"
                class="bar"
              />
              <text
                :x="69 + i * 102"
                :y="
                  region.median_f0_hz === null ? 115 : 123 - (100 * region.median_f0_hz) / regionMax
                "
                text-anchor="middle"
              >
                {{ region.median_f0_hz === null ? '有效帧不足' : `${region.median_f0_hz} Hz` }}
              </text>
              <text :x="69 + i * 102" y="159" text-anchor="middle">{{ region.label }}</text>
            </g>
          </svg>
        </figure>
      </div>
      <p class="caption">
        三段按实际选区等分；至少 3 个有效帧才显示中位 F0。清辅音、停顿没有有效 F0
        是正常现象，比例不代表发音好坏。
      </p>
    </div>
    <div
      v-if="panel === 'dimensions'"
      id="viz-dimensions"
      role="tabpanel"
      aria-labelledby="viz-tab-dimensions"
    >
      <div class="legend">
        <span>● 本次</span><span class="target">● {{ result.reference?.label || '无参照' }}</span>
      </div>
      <svg viewBox="0 0 400 255" role="img" aria-label="多维观测雷达图">
        <polygon
          v-for="ratio in [0.25, 0.5, 0.75, 1]"
          :key="ratio"
          :points="polygon(ratio)"
          class="radar-grid"
        />
        <polygon v-if="referenceReady" :points="radar(true)" class="radar-target" />
        <polygon v-if="radarReady" :points="radar()" class="radar-value" />
        <g v-for="(d, i) in dimensions" :key="d.label">
          <text :x="point(i, 1.53)[0]" :y="point(i, 1.25)[1]" text-anchor="middle">
            {{ d.label }}
          </text>
          <text :x="point(i, 1.53)[0]" :y="point(i, 1.25)[1] + 17" text-anchor="middle">
            {{ number(d.value) }} / {{ number(d.reference) }} {{ d.unit }}
          </text>
        </g>
      </svg>
      <p v-if="!radarReady" class="caption">存在未测得的维度，不连接雷达轮廓；缺失值保留为“—”。</p>
      <p class="caption">
        各轴按本次与参照较大值单独缩放，旁边保留原单位；越靠外只表示量值越大，不表示发音越好。收尾幅度取变化绝对值。
      </p>
      <h4>分段偏差</h4>
      <svg viewBox="0 0 400 185" role="img" aria-label="前中后段参照偏差柱图">
        <line x1="25" x2="375" y1="140" y2="140" class="grid" />
        <g v-for="(part, i) in evidence.deviations" :key="part.label">
          <rect
            v-if="part.value !== null"
            :x="55 + i * 115"
            :y="140 - (100 * part.value) / deviationMax"
            width="58"
            :height="(100 * part.value) / deviationMax"
            rx="5"
            class="deviation"
          />
          <text
            :x="84 + i * 115"
            :y="part.value === null ? 122 : 130 - (100 * part.value) / deviationMax"
            text-anchor="middle"
          >
            {{ part.value === null ? '不计算' : `${part.value} 半音` }}
          </text>
          <text :x="84 + i * 115" y="165" text-anchor="middle">{{ part.label }}</text>
        </g>
      </svg>
      <p class="caption">
        只比较双方均有有效 F0 的归一化时间格；不补齐空缺，不把对齐失败换算成分数。
      </p>
    </div>
    <div v-if="panel === 'energy'" id="viz-energy" role="tabpanel" aria-labelledby="viz-tab-energy">
      <svg viewBox="0 0 640 205" role="img" aria-label="实际RMS音量节奏曲线">
        <g v-for="v in [-80, -60, -40, -20, 0]" :key="v">
          <line
            x1="55"
            x2="585"
            :y1="160 - (125 * (v + 80)) / 80"
            :y2="160 - (125 * (v + 80)) / 80"
            class="grid"
          />
          <text x="45" :y="164 - (125 * (v + 80)) / 80" text-anchor="end">{{ v }}</text>
        </g>
        <path :d="energyPath" class="energy-line" />
        <text x="16" y="18">dBFS</text>
        <text
          v-for="p in [0, 0.25, 0.5, 0.75, 1]"
          :key="p"
          :x="55 + 530 * p"
          y="188"
          text-anchor="middle"
        >
          {{ p * 100 }}%
        </text>
      </svg>
      <p class="caption">
        实际 20 ms 窗口 RMS，低于 −80 dBFS 的点仅在图上裁至轴底，CSV
        保留原值。横轴为选区时间比例，低音量不自动等同于意群停顿。
      </p>
    </div>
    <div
      v-if="panel === 'history'"
      id="viz-history"
      role="tabpanel"
      aria-labelledby="viz-tab-history"
    >
      <label class="trend-control"
        >观察指标<select v-model="trendMetric" aria-label="复练轨迹指标">
          <option v-for="([label], key) in trendOptions" :key="key" :value="key">
            {{ label }}
          </option>
        </select></label
      >
      <svg viewBox="0 0 640 210" role="img" aria-label="同条件复练实测轨迹">
        <g v-for="p in [0, 0.5, 1]" :key="p">
          <line x1="55" x2="585" :y1="160 - 125 * p" :y2="160 - 125 * p" class="grid" />
          <text x="45" :y="164 - 125 * p" text-anchor="end">{{ (trendMax * p).toFixed(1) }}</text>
        </g>
        <path :d="trendPath" class="trend-line" />
        <template v-for="(item, i) in series" :key="item.id">
          <circle
            v-if="item.value !== null"
            :cx="item.x"
            :cy="y(item.value)"
            r="4"
            :class="{ current: item.id === practice.id }"
          >
            <title>
              第 {{ i + 1 }} 遍 · {{ date(item.created_at) }} · {{ item.value }}
              {{ trendOptions[trendMetric][1] }}
            </title>
          </circle>
        </template>
        <text x="55" y="187">第 1 遍</text>
        <text x="585" y="187" text-anchor="end">
          第 {{ series.length }} 遍 · {{ trendOptions[trendMetric][1] }}
        </text>
        <text v-if="!series.length" x="320" y="100" text-anchor="middle">暂无同条件记录</text>
      </svg>
      <p class="caption">
        仅比较同题目、同参照与同算法参数；缺失值保持断线，升降均如实记录。参照轮廓差越小越接近参照，其余指标不是越大越好。
      </p>
      <div class="table-scroll">
        <table>
          <thead>
            <tr>
              <th>练习时间</th>
              <th>{{ trendOptions[trendMetric][0] }}</th>
              <th>较上次</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="(item, i) in series"
              :key="item.id"
              :class="{ selected: item.id === practice.id }"
            >
              <td>{{ date(item.created_at) }}</td>
              <td>{{ number(item.value, 2) }} {{ trendOptions[trendMetric][1] }}</td>
              <td>
                {{
                  item.value !== null && i > 0 && series[i - 1].value !== null
                    ? number(item.value - (series[i - 1].value as number), 2)
                    : '—'
                }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
    <div class="repeat-section">
      <h4>复练变化</h4>
      <div v-if="changes.length" class="change-grid">
        <article v-for="change in changes" :key="change.label">
          <span>{{ change.label }}</span
          ><strong
            >{{
              change.value === null
                ? '—'
                : `${change.value >= 0 ? '+' : ''}${change.value.toFixed(2)}`
            }}
            <small>{{ change.unit }}</small></strong
          >
        </article>
      </div>
      <p v-else class="caption">在上方选择同条件的历史复练录音，可查看本次变化。</p>
      <ol class="experiment">
        <li><b>①</b>固定录音条件</li>
        <li><b>②</b>只调整一个因素</li>
        <li><b>③</b>连续三次再比较</li>
      </ol>
      <p class="caption">
        {{
          result.alignment?.status === 'unavailable'
            ? '先完整跟读当前题目并确认选区，再比较专项重音与停顿。'
            : tip
        }}
      </p>
    </div>
  </section>
</template>

<style scoped>
.dashboard {
  border: 1px solid var(--cet-line);
  border-radius: 18px;
  background: var(--cet-surface);
  padding: 24px;
  min-width: 0;
}
.dashboard-heading,
.hero,
.legend,
.viz-tabs {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
}
.eyebrow {
  font-size: 10px;
  letter-spacing: 1.5px;
  color: var(--cet-muted);
}
h3 {
  font-size: 19px;
  margin: 8px 0 0;
}
h4 {
  font-size: 14px;
  margin: 20px 0 12px;
}
.badge {
  border-radius: 20px;
  color: #15724d;
  background: #e9f7ef;
  padding: 7px 12px;
  font-size: 11px;
  white-space: nowrap;
}
.hero {
  margin-top: 22px;
  border-radius: 14px;
  background: var(--cet-surface-2);
  padding: 20px;
  align-items: start;
}
.hero span,
.change-grid span {
  font-size: 12px;
  color: var(--cet-muted);
}
.hero strong {
  font-size: 36px;
  display: block;
  margin-top: 8px;
  color: var(--cet-text);
}
small {
  font-size: 12px;
  font-weight: 400;
}
.hero p {
  font-size: 12px;
  color: var(--cet-muted);
  line-height: 1.8;
  margin: 8px 0 0;
}
.caption {
  font-size: 12px;
  color: var(--cet-muted);
  line-height: 1.9;
  margin: 12px 0;
}
.viz-tabs {
  justify-content: start;
  gap: 5px;
  background: var(--cet-surface-2);
  padding: 5px;
  border-radius: 12px;
  margin: 20px 0;
  flex-wrap: wrap;
}
button,
select {
  font: inherit;
  cursor: pointer;
  color: var(--cet-text);
}
button {
  border: 0;
  background: transparent;
  padding: 9px 13px;
  font-size: 12px;
  border-radius: 8px;
}
button[aria-selected='true'] {
  background: var(--cet-surface);
  box-shadow: 0 1px 5px #0001;
  color: var(--cet-brand);
}
.science-figures {
  display: grid;
  grid-template-columns: 0.8fr 1.4fr;
  gap: 14px;
}
figure {
  margin: 0;
  min-width: 0;
  border: 1px solid var(--cet-line);
  border-radius: 12px;
  padding: 12px;
}
figcaption {
  font-size: 12px;
  font-weight: 600;
}
svg {
  display: block;
  width: 100%;
  max-height: 300px;
  overflow: visible;
  margin: 12px auto;
}
text {
  font: 11px system-ui;
  fill: var(--cet-muted);
}
.large {
  font-size: 23px;
  font-weight: 650;
  fill: var(--cet-text);
}
.donut-base,
.donut-value {
  fill: none;
  stroke: var(--cet-line);
  stroke-width: 11;
}
.donut-value {
  stroke: #359d80;
  stroke-linecap: round;
}
.grid {
  stroke: var(--cet-line);
  stroke-dasharray: 4 4;
}
.bar {
  fill: #7c9fcb;
}
.deviation {
  fill: #e6a169;
}
.legend {
  justify-content: start;
  font-size: 12px;
  color: #2563eb;
}
.target {
  color: #cc823b;
}
.radar-grid {
  stroke: var(--cet-line);
  fill: none;
}
.radar-value {
  fill: #2563eb24;
  stroke: #2563eb;
  stroke-width: 2;
}
.radar-target {
  fill: #e6a16912;
  stroke: #cc823b;
  stroke-width: 1.5;
  stroke-dasharray: 4 3;
}
.energy-line,
.trend-line {
  fill: none;
  stroke: #359d80;
  stroke-width: 2;
}
.trend-line {
  stroke: #2563eb;
}
circle {
  fill: #7c9fcb;
}
.current {
  fill: #2563eb;
  stroke: #fff;
  stroke-width: 2;
}
.trend-control {
  display: flex;
  gap: 12px;
  align-items: center;
  font-size: 12px;
  color: var(--cet-muted);
}
select {
  padding: 7px;
  border: 1px solid var(--cet-line);
  border-radius: 8px;
  background: var(--cet-surface);
  font-size: 12px;
}
.table-scroll {
  overflow-x: auto;
}
table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
th,
td {
  text-align: left;
  padding: 11px 8px;
  border-bottom: 1px solid var(--cet-line);
  white-space: nowrap;
}
th {
  color: var(--cet-muted);
  font-weight: 500;
}
.selected {
  background: var(--cet-brand-tint);
}
.repeat-section {
  margin-top: 22px;
  padding-top: 4px;
  border-top: 1px solid var(--cet-line);
}
.change-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}
.change-grid article {
  padding: 12px;
  border-radius: 10px;
  background: var(--cet-surface-2);
}
.change-grid strong {
  font-size: 19px;
  display: block;
  margin-top: 10px;
}
.experiment {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  list-style: none;
  padding: 0;
  gap: 8px;
  margin-top: 22px;
}
.experiment li {
  font-size: 12px;
  line-height: 1.7;
  color: var(--cet-muted);
}
.experiment b {
  display: block;
  color: #359d80;
  font-size: 20px;
  margin-bottom: 5px;
}
@media (max-width: 600px) {
  .dashboard {
    padding: 16px;
  }
  .dashboard-heading,
  .hero {
    flex-wrap: wrap;
  }
  h3 {
    font-size: 17px;
  }
  .hero strong {
    font-size: 30px;
  }
  .science-figures {
    grid-template-columns: 1fr;
  }
  .change-grid {
    grid-template-columns: 1fr;
  }
  .viz-tabs {
    gap: 2px;
  }
  button {
    padding: 8px 9px;
  }
  .badge {
    font-size: 10px;
  }
}
</style>
