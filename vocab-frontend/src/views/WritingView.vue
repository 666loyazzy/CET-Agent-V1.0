<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import TopNav from '@/components/TopNav.vue'

type Level = 'CET-4' | 'CET-6'
type Evidence = {
  quote: string
  category: string
  polarity: 'supports' | 'limits'
  explanation: string
}
type FinalResult = {
  score: number
  band: number
  route: 'stable_fusion' | 'chief_examiner' | 'invalid'
  summary: string
  strengths: string[]
  priorities: string[]
  evidence: Evidence[]
}

const level = ref<Level>('CET-4')
const topic = ref('')
const essay = ref('')
const running = ref(false)
const error = ref('')
const result = ref<FinalResult | null>(null)
const progress = ref<string[]>([])
const wordCount = computed(() => essay.value.match(/[A-Za-z]+(?:'[A-Za-z]+)?/g)?.length ?? 0)

const NODE_LABELS: Record<string, string> = {
  precheck: '检查题目与字数',
  calibrate: '加载 CET 评分标准',
  strict_rater: '严格评审完成',
  lenient_rater: '宽松评审完成',
  reliability_gate: '一致性检查完成',
  additional_scoring: '追加评审完成',
  dispatch_review: '进入争议复核',
  language_evidence: '语言专家完成',
  task_content_evidence: '任务与内容专家完成',
  coherence_evidence: '连贯性专家完成',
  critic: '批评者复核完成',
  chief_examiner: '主考官裁决完成',
  fuse: '评分融合完成',
  invalid: '作文不满足评分条件',
}

onMounted(() => {
  const saved = localStorage.getItem('cet-agent-level')
  if (saved === 'CET-4' || saved === 'CET-6') level.value = saved
})

function onLevelChange(value: Level) {
  level.value = value
}

async function review() {
  if (!topic.value.trim() || !essay.value.trim() || running.value) return
  running.value = true
  error.value = ''
  result.value = null
  progress.value = []
  try {
    const response = await fetch('/api/writing/review-stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ topic: topic.value.trim(), essay: essay.value.trim(), level: level.value }),
    })
    if (!response.ok || !response.body) throw new Error(`HTTP ${response.status}`)
    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')
      let boundary = buffer.indexOf('\n\n')
      while (boundary >= 0) {
        handleFrame(buffer.slice(0, boundary))
        buffer = buffer.slice(boundary + 2)
        boundary = buffer.indexOf('\n\n')
      }
    }
  } catch (reason: any) {
    error.value = reason?.message || String(reason)
  } finally {
    running.value = false
  }
}

function handleFrame(frame: string) {
  let event = 'message'
  let raw = ''
  for (const line of frame.split('\n')) {
    if (line.startsWith('event:')) event = line.slice(6).trim()
    if (line.startsWith('data:')) raw += line.slice(5).trim()
  }
  if (!raw) return
  const payload = JSON.parse(raw)
  if (event === 'error') error.value = payload.message || '评分失败'
  if (event !== 'node') return
  progress.value.push(NODE_LABELS[payload.node] || payload.node)
  if (payload.data?.final_result) result.value = payload.data.final_result
}
</script>

<template>
  <TopNav active="writing" @level-change="onLevelChange" />
  <div class="writing-wrap">
    <main class="writing-page">
      <header>
        <h1>作文多智能体评审</h1>
        <p>严格评审与宽松评审独立打分；意见不一致时自动交给专家组和主考官。</p>
      </header>

      <section class="panel form-panel">
        <label>
          <span>作文题目</span>
          <textarea v-model="topic" rows="3" :disabled="running" placeholder="粘贴 CET-4 / CET-6 作文题目与要求"></textarea>
        </label>
        <label>
          <span>作文正文</span>
          <textarea v-model="essay" rows="12" :disabled="running" placeholder="Paste your essay here..."></textarea>
        </label>
        <div class="form-foot">
          <span>{{ level }} · {{ wordCount }} words</span>
          <button :disabled="running || !topic.trim() || !essay.trim()" @click="review">
            {{ running ? '多智能体评审中…' : '开始评审' }}
          </button>
        </div>
      </section>

      <section v-if="progress.length" class="panel progress-panel">
        <h2>评审进度</h2>
        <div class="steps">
          <span v-for="(step, index) in progress" :key="`${step}-${index}`">✓ {{ step }}</span>
        </div>
      </section>

      <p v-if="error" class="error">{{ error }}</p>

      <section v-if="result" class="panel result-panel">
        <div class="score">
          <strong>{{ result.score }}</strong><span>/ 15</span>
          <small>档位 {{ result.band }} · {{ result.route === 'chief_examiner' ? '主考官裁决' : result.route === 'invalid' ? '不可评分' : '一致性融合' }}</small>
        </div>
        <div class="result-body">
          <p class="summary">{{ result.summary }}</p>
          <div class="columns">
            <div><h3>优点</h3><ul><li v-for="item in result.strengths" :key="item">{{ item }}</li><li v-if="!result.strengths.length">暂无</li></ul></div>
            <div><h3>优先改进</h3><ul><li v-for="item in result.priorities" :key="item">{{ item }}</li><li v-if="!result.priorities.length">暂无</li></ul></div>
          </div>
          <div v-if="result.evidence.length" class="evidence">
            <h3>原文证据</h3>
            <article v-for="(item, index) in result.evidence" :key="index" :class="item.polarity">
              <q>{{ item.quote }}</q><p>{{ item.explanation }}</p>
            </article>
          </div>
        </div>
      </section>
    </main>
  </div>
</template>

<style scoped>
.writing-wrap { height: calc(100vh - var(--cet-nav-h)); overflow-y: auto; background: var(--cet-body-bg); color: var(--cet-text); font-family: var(--cet-font); }
.writing-page { max-width: 920px; margin: 0 auto; padding: 28px 20px 64px; }
header { margin-bottom: 20px; }
h1 { margin: 0; color: var(--cet-ink); font-size: 26px; }
header p { margin: 7px 0 0; color: var(--cet-muted); font-size: 13px; }
.panel { background: var(--cet-card-bg); border: 1px solid var(--cet-card-border); border-radius: 12px; padding: 20px; margin-bottom: 16px; }
label { display: block; margin-bottom: 16px; }
label span, h2, h3 { display: block; color: var(--cet-ink); font-weight: 600; }
label span { margin-bottom: 7px; font-size: 13px; }
textarea { width: 100%; box-sizing: border-box; resize: vertical; border: 1px solid var(--cet-input-border); border-radius: 7px; background: var(--cet-input-bg); color: var(--cet-input-text); padding: 10px 12px; font: 14px/1.6 var(--cet-font); outline: none; }
textarea:focus { border-color: var(--cet-brand); box-shadow: 0 0 0 2px var(--cet-brand-tint); }
.form-foot { display: flex; align-items: center; justify-content: space-between; color: var(--cet-muted); font-size: 12px; }
button { border: 0; border-radius: 7px; padding: 9px 20px; background: var(--cet-brand); color: var(--cet-brand-fg); font-weight: 600; cursor: pointer; }
button:disabled { opacity: .5; cursor: not-allowed; }
h2 { margin: 0 0 12px; font-size: 15px; }
.steps { display: flex; flex-wrap: wrap; gap: 8px; }
.steps span { padding: 5px 9px; border-radius: 5px; background: var(--cet-brand-tint); color: var(--cet-brand-deep); font-size: 12px; }
.error { padding: 12px 15px; border-radius: 7px; background: var(--cet-verdict-bad-bg); color: var(--cet-verdict-bad-fg); }
.result-panel { display: grid; grid-template-columns: 150px 1fr; gap: 24px; }
.score strong { display: block; color: var(--cet-brand); font-size: 64px; line-height: 1; }
.score span { color: var(--cet-muted); }
.score small { display: block; margin-top: 9px; color: var(--cet-muted); line-height: 1.5; }
.summary { margin-top: 0; line-height: 1.7; }
.columns { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
h3 { margin: 10px 0 6px; font-size: 13px; }
ul { margin: 0; padding-left: 20px; line-height: 1.7; font-size: 13px; }
.evidence article { border-left: 3px solid var(--cet-brand); padding: 8px 12px; margin-top: 9px; background: var(--cet-surface-2); font-size: 13px; }
.evidence article.limits { border-left-color: var(--cet-verdict-bad-fg); }
.evidence q { color: var(--cet-ink); font-weight: 600; }
.evidence p { margin: 5px 0 0; color: var(--cet-muted); }
@media (max-width: 700px) { .result-panel, .columns { grid-template-columns: 1fr; } .score strong { font-size: 48px; } }
</style>
