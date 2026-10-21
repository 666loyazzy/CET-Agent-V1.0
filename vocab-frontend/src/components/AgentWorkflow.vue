<script setup lang="ts">
import { computed, ref, onMounted, onBeforeUnmount, nextTick, watch } from 'vue'

export type Step = {
  id: string
  status: string
  started_at: number
  finished_at?: number
  skill_version?: string
  message?: string
}
const props = defineProps<{ trace: Step[]; busy?: boolean; teaching?: boolean }>()
const stages = computed(() =>
  props.teaching
    ? [
        ['coach.context', '读取实测与记忆'],
        ['coach.skills', '加载教学规范'],
        ['coach.generate', '生成针对性建议'],
        ['coach.validate', '校验测量依据'],
        ['coach.save', '保存教学记录']
      ]
    : [
        ['audio.decode', '音频解码'],
        ['audio.quality', '录音质量检查'],
        ['praat.extract', 'Praat 音高提取'],
        ['text.align', '英文词语定位'],
        ['prosody.features', '韵律特征计算'],
        ['prosody.assess', '专项证据分析'],
        ['chart.validate', '图表数据校验'],
        ['reference.compare', '参照与复练条件'],
        ['memory.update', '保存练习与记忆']
      ]
)
const completed = computed(
  () => props.trace.filter((s) => ['completed', 'warning'].includes(s.status)).length
)
const diagram = ref<HTMLElement | null>(null)
const connections = ref<{ d: string; status: string }[]>([])
const diagramSize = ref('0 0 1 1')
const marker = computed(() => (props.teaching ? 'coach-edge-arrow' : 'analysis-edge-arrow'))
let observer: ResizeObserver | undefined
async function drawConnections() {
  await nextTick()
  if (!diagram.value) return
  const bounds = diagram.value.getBoundingClientRect()
  if (!bounds.width) return
  const nodes = [...diagram.value.querySelectorAll('li')].map((node) =>
    node.getBoundingClientRect()
  )
  diagramSize.value = `0 0 ${bounds.width} ${bounds.height}`
  connections.value = nodes.slice(0, -1).map((node, i) => {
    const next = nodes[i + 1]
    const x1 = node.right - bounds.left,
      y1 = (node.top + node.bottom) / 2 - bounds.top
    const x2 = next.left - bounds.left,
      y2 = (next.top + next.bottom) / 2 - bounds.top
    const middle = (node.bottom + next.top) / 2 - bounds.top
    return {
      d:
        Math.abs(y1 - y2) < 5
          ? `M${x1},${y1}L${x2},${y2}`
          : `M${x1},${y1}H${x1 + 6}V${middle}H${x2 - 6}V${y2}H${x2}`,
      status: step(stages.value[i][0])?.status || 'pending'
    }
  })
}
onMounted(() => {
  observer = new ResizeObserver(drawConnections)
  if (diagram.value) observer.observe(diagram.value)
  drawConnections()
})
watch(() => props.trace, drawConnections, { deep: true })
onBeforeUnmount(() => observer?.disconnect())
function step(id: string) {
  return props.trace.find((s) => s.id === id)
}
function duration(id: string) {
  const s = step(id)
  return s?.finished_at
    ? `${Math.max(0, s.finished_at - s.started_at).toFixed(2)}s`
    : s?.status === 'running'
      ? '执行中'
      : '等待'
}
</script>

<template>
  <section class="workflow" aria-label="智能体工作进度" aria-live="polite">
    <div class="flow-head">
      <div>
        <span class="flow-kicker">{{ teaching ? 'COACH AGENT' : 'ANALYSIS HARNESS' }}</span>
        <h3>{{ teaching ? '教学智能体工作进度' : '声学分析工作进度' }}</h3>
      </div>
      <span class="flow-count">{{ completed }} / {{ stages.length }} 已处理</span>
    </div>
    <div ref="diagram" class="flow-diagram">
      <svg class="connections" :viewBox="diagramSize" aria-hidden="true">
        <defs>
          <marker :id="marker" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
            <path d="M0,0L6,3L0,6" fill="currentColor" />
          </marker>
        </defs>
        <path
          v-for="(edge, i) in connections"
          :key="i"
          :d="edge.d"
          :class="edge.status"
          :marker-end="`url(#${marker})`"
        />
      </svg>
      <ol class="flow-grid">
        <li
          v-for="([id, label], index) in stages"
          :key="id"
          :class="step(id)?.status || 'pending'"
          :data-stage="id"
        >
          <span class="node-icon">{{
            step(id)?.status === 'completed'
              ? '✓'
              : ['failed', 'warning'].includes(step(id)?.status || '')
                ? '!'
                : String(index + 1).padStart(2, '0')
          }}</span>
          <div class="node-text">
            <strong>{{ label }}</strong
            ><small
              >{{ duration(id)
              }}<span v-if="step(id)?.skill_version">
                · {{ step(id)?.skill_version?.slice(0, 6) }}</span
              ></small
            >
            <small v-if="step(id)?.message" class="step-message">{{ step(id)?.message }}</small>
          </div>
        </li>
      </ol>
    </div>
    <p>
      {{
        trace.some((s) => s.status === 'failed')
          ? '失败步骤已保留，下游步骤停止执行。'
          : trace.some((s) => s.status === 'warning')
            ? '黄色节点表示局部受限：实测图表已保留，对齐相关判断暂缓。'
            : busy
              ? '显示后台实际执行状态。分析期间可以回听录音。'
              : trace.length
                ? '每一步均记录实际开始、结束时间；记录随练习保存。'
                : '提交后逐步显示实际状态、耗时与完成结果。'
      }}
    </p>
  </section>
</template>

<style scoped>
.workflow {
  background: var(--cet-surface);
  border: 1px solid var(--cet-line);
  border-radius: 18px;
  padding: 24px;
}
.flow-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
}
.flow-kicker {
  font-size: 10px;
  letter-spacing: 2px;
  color: var(--cet-muted);
}
h3 {
  margin: 7px 0 0;
  font-size: 17px;
}
.flow-count {
  font-size: 12px;
  color: var(--cet-muted);
}
.flow-grid {
  list-style: none;
  padding: 0;
  margin: 25px 0 16px;
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 13px 26px;
}
.flow-diagram {
  position: relative;
}
.connections {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  overflow: visible;
  pointer-events: none;
  color: var(--cet-muted);
}
.connections > path {
  fill: none;
  stroke: var(--cet-line);
  stroke-width: 1.4;
}
.connections > path.completed {
  stroke: #359d80;
}
.connections > path.warning {
  stroke: #d69a3a;
}
.step-message {
  line-height: 1.7;
}
.flow-grid li {
  position: relative;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 15px 12px;
  border: 1px solid var(--cet-line);
  border-radius: 12px;
  min-height: 70px;
}
.node-icon {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  background: var(--cet-surface-2);
  font-size: 11px;
  font-weight: 700;
  color: var(--cet-muted);
  flex-shrink: 0;
}
.node-text {
  min-width: 0;
}
strong {
  font-size: 12px;
  display: block;
}
small {
  display: block;
  margin-top: 6px;
  font-size: 10px;
  color: var(--cet-muted);
}
.warning {
  border-color: #d69a3a !important;
}
.warning .node-icon {
  background: #fff1cf;
  color: #8d5a08;
}
.completed {
  background: #ecfdf51a;
  border-color: #4ca98366 !important;
}
.completed .node-icon {
  background: #d4f4e4;
  color: #176444;
}
.running {
  border-color: #2563eb !important;
  background: #2563eb0a;
}
.running .node-icon {
  background: #2563eb;
  color: white;
  animation: pulse 1.2s ease-in-out infinite;
}
.failed {
  border-color: #e0716c !important;
}
.failed .node-icon {
  background: #fee2e2;
  color: #b42318;
}
p {
  font-size: 12px;
  line-height: 1.7;
  color: var(--cet-muted);
  margin-bottom: 0;
}
@keyframes pulse {
  50% {
    box-shadow: 0 0 0 5px #2563eb22;
  }
}
@media (prefers-reduced-motion: reduce) {
  .running .node-icon {
    animation: none;
  }
}
@media (max-width: 650px) {
  .workflow {
    padding: 16px;
  }
  .flow-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 10px;
  }
  .flow-grid li {
    padding: 10px 7px;
    gap: 7px;
  }
  .node-icon {
    width: 22px;
    height: 22px;
  }
  .flow-count {
    font-size: 10px;
  }
}
</style>
