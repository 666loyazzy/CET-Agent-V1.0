<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import TopNav from '@/components/TopNav.vue'
import ProsodyChart from '@/components/ProsodyChart.vue'
import PronunciationDashboard from '@/components/PronunciationDashboard.vue'
import AgentWorkflow, { type Step } from '@/components/AgentWorkflow.vue'
import { usePronunciationRecorder } from '@/composables/usePronunciationRecorder'
import { speechApi, type Exercise, type Practice, type Memory } from '@/api/pronunciation'

const groups = [
  { id: 'word_stress', label: '单词重音', en: 'WORD STRESS', icon: 'Aa' },
  { id: 'sentence_stress', label: '句子重音', en: 'SENTENCE STRESS', icon: '↗' },
  { id: 'intonation', label: '语调练习', en: 'INTONATION', icon: '∿' },
  { id: 'rhythm', label: '节奏与停顿', en: 'RHYTHM', icon: 'Ⅱ' }
]
const exercises = ref<Exercise[]>([])
const selectedId = ref('present-noun')
const group = ref('word_stress')
const tab = ref<'practice' | 'compare' | 'history'>('practice')
const selected = computed(() => exercises.value.find((e) => e.id === selectedId.value))
const filtered = computed(() => exercises.value.filter((e) => e.kind === group.value))
const error = ref('')
const notice = ref('')
const available = ref<boolean | null>(null)
const file = ref<Blob | null>(null)
const fileName = ref('')
const previewUrl = ref('')
const confirmed = ref(false)
const busy = ref(false)
const waited = ref(0)
const current = ref<Practice | null>(null)
const history = ref<Practice[]>([])
const memory = ref<Memory>({ enabled: true, patterns: {}, facts: [] })
const comparisonId = ref('')
const comparison = ref<Practice | null>(null)
const learnerAudio = ref<HTMLAudioElement | null>(null)
const referenceAudio = ref<HTMLAudioElement | null>(null)
const inputAudio = ref<HTMLAudioElement | null>(null)
const start = ref('')
const end = ref('')
const floor = ref(60)
const ceiling = ref(600)
const referenceId = ref('builtin')
const coachQuestion = ref('')
const coachAnswer = ref('')
const coachSource = ref('')
const coachBusy = ref(false)
const coachModel = ref(localStorage.getItem('cet-agent-speaking-model') || 'deepseek-flash')
const coachTrace = ref<Step[]>([])
const alteredUrl = ref('')
const altering = ref(false)
let pollTimer: ReturnType<typeof setTimeout> | undefined
let waitTimer: ReturnType<typeof setInterval> | undefined
let clipTimer: ReturnType<typeof setTimeout> | undefined
let disposed = false
const result = computed(() =>
  current.value?.status === 'completed' ? current.value.result : undefined
)
const trace = computed(() => (current.value?.trace || result.value?.trace || []) as Step[])
const personalReferences = computed(() =>
  history.value.filter(
    (p) => p.is_reference && p.exercise_id === selectedId.value && p.status === 'completed'
  )
)
const comparable = computed(() =>
  history.value.filter(
    (p) =>
      p.exercise_id === selectedId.value &&
      p.status === 'completed' &&
      p.id !== current.value?.id &&
      !p.is_reference
  )
)
const pendingRecording = computed(() => recorder.state.value !== 'idle')
const locked = computed(() => busy.value || pendingRecording.value || coachBusy.value)
const statusLabels: Record<string, string> = {
  matched: '符合练习目标',
  close: '接近目标 · 回听确认',
  adjust: '建议调整',
  uncertain: '暂不判断'
}
const patternLabels: Record<string, string> = {
  word_stress: '单词重音',
  sentence_stress: '句子重音',
  intonation: '句尾语调',
  phrase_boundary: '意群停顿'
}

function receiveRecording(blob: Blob, name = '本次录音') {
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  previewUrl.value = URL.createObjectURL(blob)
  file.value = blob
  fileName.value = name
  confirmed.value = false
  start.value = ''
  end.value = ''
  error.value = ''
}
const recorder = usePronunciationRecorder(receiveRecording)

function chooseExercise(id: string) {
  if (locked.value) return
  selectedId.value = id
  current.value = null
  comparison.value = null
  comparisonId.value = ''
  coachAnswer.value = ''
  coachTrace.value = []
  if (alteredUrl.value) URL.revokeObjectURL(alteredUrl.value)
  alteredUrl.value = ''
  referenceId.value = 'builtin'
  confirmed.value = false
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  previewUrl.value = ''
  file.value = null
  fileName.value = ''
  start.value = ''
  end.value = ''
  error.value = ''
  notice.value = ''
}
function chooseGroup(id: string) {
  if (locked.value) return
  group.value = id
  const first = exercises.value.find((e) => e.kind === id)
  if (first) chooseExercise(first.id)
}
function upload(event: Event) {
  const input = event.target as HTMLInputElement
  const candidate = input.files?.[0]
  if (candidate) {
    if (candidate.size > 12 * 1024 * 1024) error.value = '文件最多 12 MB。'
    else receiveRecording(candidate, candidate.name)
  }
  input.value = ''
}
function browserSample() {
  if (!selected.value || !('speechSynthesis' in window)) {
    error.value = '浏览器朗读不可用，请播放内置示范或上传参照音。'
    return
  }
  speechSynthesis.cancel()
  const speech = new SpeechSynthesisUtterance(selected.value.text)
  speech.lang = 'en-US'
  speech.rate = 0.85
  const voice = speechSynthesis.getVoices().find((v) => v.lang === 'en-US')
  if (voice) speech.voice = voice
  speechSynthesis.speak(speech)
}
async function refresh() {
  const [practices, memories] = await Promise.all([
    speechApi<Practice[]>('/practices'),
    speechApi<Memory>('/memory')
  ])
  history.value = practices
  memory.value = memories
}
async function poll(id: string) {
  if (disposed) return
  try {
    const state = await speechApi<Practice>(`/practices/${id}`)
    if (disposed) return
    current.value = state
    if (['completed', 'failed'].includes(state.status)) {
      busy.value = false
      clearInterval(waitTimer)
      if (state.error) error.value = state.error
      await refresh()
      return
    }
    pollTimer = setTimeout(() => poll(id), 450)
  } catch (caught) {
    busy.value = false
    clearInterval(waitTimer)
    error.value = caught instanceof Error ? caught.message : '状态读取失败。录音仍可重新提交。'
  }
}
async function submit() {
  if (!file.value || !confirmed.value || locked.value) return
  if ((start.value === '') !== (end.value === '')) {
    error.value = '请同时填写选区起止时间，或都留空。'
    return
  }
  if (
    start.value !== '' &&
    !(Number(start.value) >= 0 && Number(end.value) > Number(start.value))
  ) {
    error.value = '选区终点需要晚于起点。'
    return
  }
  busy.value = true
  error.value = ''
  notice.value = ''
  waited.value = 0
  current.value = null
  coachAnswer.value = ''
  coachTrace.value = []
  comparison.value = null
  comparisonId.value = ''
  const body = new FormData()
  body.set('file', file.value, 'recording.audio')
  body.set('exercise_id', selectedId.value)
  body.set('read_confirmed', 'true')
  body.set('pitch_floor', String(floor.value))
  body.set('pitch_ceiling', String(ceiling.value))
  body.set('reference_id', referenceId.value)
  if (start.value !== '') {
    body.set('start_s', start.value)
    body.set('end_s', end.value)
  }
  waitTimer = setInterval(() => waited.value++, 1000)
  try {
    const state = await speechApi<{ id: string }>('/analyses', { method: 'POST', body })
    await poll(state.id)
  } catch (caught) {
    busy.value = false
    clearInterval(waitTimer)
    error.value = caught instanceof Error ? caught.message : '提交未完成。'
  }
}
async function openPractice(item: Practice) {
  if (locked.value) return
  const exercise = exercises.value.find((e) => e.id === item.exercise_id)
  if (exercise) {
    group.value = exercise.kind
    chooseExercise(exercise.id)
  }
  try {
    current.value = await speechApi<Practice>(`/practices/${item.id}`)
    tab.value = 'practice'
    error.value = current.value.error || ''
    const messages = await speechApi<{ answer: string; source: string; trace: Step[] }[]>(
      `/practices/${item.id}/coaching`
    )
    if (messages[0]) {
      coachAnswer.value = messages[0].answer
      coachSource.value = messages[0].source === 'local' ? '本地实测建议' : '模型教学建议'
      coachTrace.value = messages[0].trace
    }
  } catch (caught) {
    error.value = (caught as Error).message
  }
}
async function restoreRecording() {
  if (!current.value || locked.value) return
  try {
    const response = await fetch(current.value.audio_url, { credentials: 'same-origin' })
    if (!response.ok) throw new Error('原录音读取失败，可能已超过保留期。')
    receiveRecording(await response.blob(), '历史录音 · 请重新确认题目与选区')
    notice.value = '原录音已载入。请回听、确认当前题目与选区后重新分析；不会覆盖原记录。'
  } catch (caught) {
    error.value = (caught as Error).message
  }
}
async function removePractice(item: Practice) {
  if (!window.confirm('删除这次录音、分析和对应教学记录？')) return
  try {
    await speechApi(`/practices/${item.id}`, { method: 'DELETE' })
    if (current.value?.id === item.id) current.value = null
    await refresh()
  } catch (caught) {
    error.value = (caught as Error).message
  }
}
async function makeReference() {
  if (!current.value) return
  try {
    await speechApi(`/practices/${current.value.id}/reference`, { method: 'POST' })
    referenceId.value = current.value.id
    notice.value = '已设为本题的个人参照，后续提交可选用。'
    await refresh()
  } catch (caught) {
    error.value = (caught as Error).message
  }
}
function seek(time: number, endTime?: number) {
  const player = learnerAudio.value
  if (!player) return
  clearTimeout(clipTimer)
  player.currentTime = time
  player.play().catch(() => {
    error.value = '请先点击录音播放器，再播放片段。'
  })
  if (endTime !== undefined)
    clipTimer = setTimeout(() => player.pause(), Math.max(0.2, endTime - time) * 1000)
}
function playSelection() {
  const player = inputAudio.value
  if (!player) return
  clearTimeout(clipTimer)
  player.currentTime = Number(start.value || 0)
  player.play().catch(() => {})
  if (end.value)
    clipTimer = setTimeout(
      () => player.pause(),
      Math.max(0.2, Number(end.value) - Number(start.value || 0)) * 1000
    )
}
async function changeMemory(enabled?: boolean, clear = false) {
  try {
    memory.value = await speechApi<Memory>('/memory', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled, clear })
    })
  } catch (caught) {
    error.value = (caught as Error).message
  }
}
async function askCoach() {
  if (!current.value || coachBusy.value) return
  coachBusy.value = true
  coachAnswer.value = ''
  coachTrace.value = []
  error.value = ''
  localStorage.setItem('cet-agent-speaking-model', coachModel.value)
  try {
    const response = await fetch(`/api/speaking/practices/${current.value.id}/coach-stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        question: coachQuestion.value || '这次应该如何改进？',
        model: coachModel.value
      })
    })
    if (!response.ok || !response.body) throw new Error('教学建议暂时不可用，请稍后重试。')
    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    while (true) {
      const { done, value } = await reader.read()
      buffer += decoder.decode(value, { stream: !done }).replace(/\r\n/g, '\n')
      let boundary: number
      while ((boundary = buffer.indexOf('\n\n')) !== -1) {
        const block = buffer.slice(0, boundary)
        buffer = buffer.slice(boundary + 2)
        const event = block
          .split('\n')
          .find((line) => line.startsWith('event: '))
          ?.slice(7)
        const data = block
          .split('\n')
          .find((line) => line.startsWith('data: '))
          ?.slice(6)
        if (!data) continue
        const payload = JSON.parse(data)
        if (event === 'trace') coachTrace.value = payload.trace
        if (event === 'result') {
          coachAnswer.value = payload.answer
          coachSource.value = payload.source === 'local' ? '本地实测建议' : '模型教学建议'
          if (payload.notice) notice.value = payload.notice
        }
        if (event === 'error') throw new Error(payload.message)
      }
      if (done) break
    }
  } catch (caught) {
    error.value = (caught as Error).message
  } finally {
    coachBusy.value = false
  }
}
function exportData() {
  if (!result.value) return
  const chart = result.value.chart
  const content = [
    'time_s,f0_hz,relative_semitones,energy_dbfs',
    ...chart.time_s.map(
      (t, i) => `${t},${chart.f0_hz[i] ?? ''},${chart.semitones[i] ?? ''},${chart.energy_dbfs[i]}`
    )
  ].join('\n')
  const url = URL.createObjectURL(new Blob([content], { type: 'text/csv;charset=utf-8' }))
  const link = document.createElement('a')
  link.href = url
  link.download = `pronunciation-${current.value?.id}.csv`
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
async function alteredSample() {
  if (!current.value || altering.value) return
  altering.value = true
  try {
    const response = await fetch(`/api/speaking/practices/${current.value.id}/resynthesis`, {
      method: 'POST'
    })
    if (!response.ok) throw new Error('当前录音不适合生成试听，请检查参照和录音质量。')
    if (alteredUrl.value) URL.revokeObjectURL(alteredUrl.value)
    alteredUrl.value = URL.createObjectURL(await response.blob())
  } catch (caught) {
    error.value = (caught as Error).message
  } finally {
    altering.value = false
  }
}
watch(comparisonId, async (id) => {
  comparison.value = null
  if (!id || !result.value) return
  try {
    const item = await speechApi<Practice>(`/practices/${id}`)
    if (item.result?.comparison_key !== result.value.comparison_key) {
      notice.value = '这两次练习的参照或音高参数不同，暂不直接比较。'
      comparisonId.value = ''
      return
    }
    comparison.value = item
  } catch (caught) {
    error.value = (caught as Error).message
  }
})
onMounted(async () => {
  try {
    const catalog = await speechApi<{ exercises: Exercise[] }>('/catalog')
    exercises.value = catalog.exercises
    await refresh()
    const state = await speechApi<{ available: boolean }>('/status')
    available.value = state.available
    const unfinished = history.value.find((p) => ['queued', 'processing'].includes(p.status))
    if (unfinished) {
      const exercise = exercises.value.find((e) => e.id === unfinished.exercise_id)
      if (exercise) {
        selectedId.value = exercise.id
        group.value = exercise.kind
      }
      busy.value = true
      waitTimer = setInterval(() => waited.value++, 1000)
      await poll(unfinished.id)
    }
  } catch (caught) {
    error.value = (caught as Error).message
  }
})
onBeforeUnmount(() => {
  disposed = true
  clearTimeout(pollTimer)
  clearInterval(waitTimer)
  clearTimeout(clipTimer)
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  if (alteredUrl.value) URL.revokeObjectURL(alteredUrl.value)
  if ('speechSynthesis' in window) speechSynthesis.cancel()
})
</script>

<template>
  <TopNav active="pronunciation" />
  <main class="pronunciation-page">
    <header class="page-heading">
      <div>
        <p class="eyebrow">SPEAK WITH INTENTION</p>
        <h1>英语发音训练<span>把每一次练习，变成听得见的进步。</span></h1>
        <p class="intro">从重音到语调，听示范、看证据，再练一次。</p>
      </div>
      <span class="service-status" :class="{ offline: available === false }"
        ><i />{{
          available === null
            ? '正在连接分析服务'
            : available
              ? '本地声学分析已就绪'
              : '声学服务未连接'
        }}</span
      >
    </header>
    <div class="page-tabs" role="tablist" aria-label="训练页面">
      <button
        v-for="item in [
          { id: 'practice', label: '专项训练' },
          { id: 'compare', label: '复练对比' },
          { id: 'history', label: '练习记录' }
        ]"
        :key="item.id"
        role="tab"
        :aria-selected="tab === item.id"
        @click="tab = item.id as typeof tab"
      >
        {{ item.label }}<span v-if="item.id === 'history'">{{ history.length }}</span>
      </button>
    </div>
    <div v-if="error || recorder.error.value" class="message error" role="alert">
      {{ error || recorder.error.value }}
    </div>
    <div v-if="notice" class="message notice" role="status">{{ notice }}</div>
    <div v-if="available === false" class="message notice">
      分析服务未启动。仍可录音回听；启动服务后可重新提交。
    </div>

    <div v-if="tab !== 'history'" class="training-layout">
      <aside class="training-sidebar">
        <span class="section-label">训练方向</span
        ><button
          v-for="item in groups"
          :key="item.id"
          :disabled="locked"
          :class="['category-button', { selected: group === item.id }]"
          @click="chooseGroup(item.id)"
        >
          <span class="category-icon">{{ item.icon }}</span
          ><span
            ><strong>{{ item.label }}</strong
            ><small>{{ item.en }}</small></span
          ><span class="category-arrow">›</span>
        </button>
        <div class="sidebar-tip">
          <span>练习小贴士</span>
          <p>保持相同的麦克风距离和音量。先完整回听，再决定下一次要改什么。</p>
        </div>
        <div class="memory-card">
          <div class="memory-head">
            <strong>我的练习记忆</strong
            ><input
              type="checkbox"
              aria-label="开启练习记忆"
              :checked="memory.enabled"
              @change="changeMemory(($event.target as HTMLInputElement).checked)"
            />
          </div>
          <p v-if="!memory.enabled">已关闭，不向教学模型提供历史摘要。</p>
          <p v-else-if="!Object.keys(memory.patterns).length">
            完成练习后，这里会整理可复练的问题。
          </p>
          <p v-for="(count, code) in memory.patterns" :key="code">
            {{ patternLabels[code] || code }} <strong>{{ count }} 次待调整</strong>
          </p>
          <button class="text-button" @click="changeMemory(undefined, true)">清空记忆摘要</button>
        </div>
      </aside>
      <div class="training-content">
        <section v-if="selected" class="practice-card">
          <div class="card-topline">
            <span class="exercise-badge">{{ groups.find((g) => g.id === group)?.label }}</span
            ><span class="quiet"
              >{{ filtered.findIndex((e) => e.id === selectedId) + 1 }} /
              {{ filtered.length }}</span
            >
          </div>
          <div class="exercise-options">
            <button
              v-for="exercise in filtered"
              :key="exercise.id"
              :disabled="locked"
              :class="{ active: selectedId === exercise.id }"
              @click="chooseExercise(exercise.id)"
            >
              {{ exercise.title }}
            </button>
          </div>
          <p class="exercise-context">{{ selected.context }}</p>
          <h2 lang="en">{{ selected.display }}</h2>
          <p class="exercise-tip">{{ selected.tip }}</p>
          <div class="reference-controls">
            <audio
              v-if="selected.reference_available"
              ref="referenceAudio"
              :key="selectedId"
              :src="`/api/speaking/samples/${selectedId}`"
              controls
              preload="none"
              aria-label="合成练习示范"
            /><button v-else class="secondary" @click="browserSample">▷ 浏览器朗读</button
            ><span class="quiet">合成练习示范 · 非教师金标</span>
          </div>
        </section>

        <section v-if="tab === 'practice'" class="record-card">
          <div class="section-title">
            <div>
              <h3>轮到你了</h3>
              <p>完整读出上方文本，单次最长 30 秒。</p>
            </div>
            <span class="record-time"
              >{{ recorder.elapsed.value.toFixed(1) }} <small>/ 30s</small></span
            >
          </div>
          <div class="record-center">
            <div
              class="microphone-orbit"
              :class="{ recording: recorder.state.value === 'recording' }"
            >
              <button
                v-if="recorder.state.value === 'recording'"
                class="mic-button stop"
                aria-label="停止录音"
                @click="recorder.stop"
              >
                <span>■</span></button
              ><button
                v-else
                class="mic-button"
                :disabled="busy || pendingRecording || coachBusy"
                aria-label="开始录音"
                @click="recorder.start"
              >
                <svg width="29" height="34" viewBox="0 0 29 34" fill="none" aria-hidden="true">
                  <rect
                    x="10"
                    y="2"
                    width="9"
                    height="18"
                    rx="4.5"
                    stroke="currentColor"
                    stroke-width="2"
                  />
                  <path
                    d="M5 15v3a9.5 9.5 0 0 0 19 0v-3M14.5 28v4M9 32h11"
                    stroke="currentColor"
                    stroke-width="2"
                    stroke-linecap="round"
                  />
                </svg>
              </button>
            </div>
            <strong>{{
              recorder.state.value === 'requesting'
                ? '等待麦克风授权…'
                : recorder.state.value === 'recording'
                  ? '正在录音，读完后点击停止'
                  : '点击麦克风，开始这一遍'
            }}</strong>
            <div class="level-meter" aria-label="实时录音音量">
              <i :style="{ width: `${recorder.level.value * 100}%` }" />
            </div>
            <button
              v-if="recorder.state.value === 'requesting'"
              class="text-button"
              @click="recorder.cancel"
            >
              取消等待</button
            ><label class="upload-button" :class="{ disabled: locked }"
              >上传已有录音<input
                type="file"
                accept="audio/*,.m4a,.webm,.wav,.mp3,.ogg"
                :disabled="locked"
                @change="upload"
            /></label>
          </div>
          <div v-if="previewUrl" class="preview">
            <div class="preview-heading">
              <strong>{{ fileName }}</strong
              ><a :href="previewUrl" download="pronunciation-recording.audio">下载录音</a>
            </div>
            <audio
              ref="inputAudio"
              :src="previewUrl"
              controls
              preload="metadata"
              aria-label="提交前录音回听"
            />
            <details>
              <summary>选区、音高范围与参照</summary>
              <div class="options-grid">
                <label
                  >起点（秒）<input
                    v-model="start"
                    type="number"
                    min="0"
                    step=".01"
                    placeholder="自动"
                    :disabled="busy" /></label
                ><label
                  >终点（秒）<input
                    v-model="end"
                    type="number"
                    min=".2"
                    step=".01"
                    placeholder="自动"
                    :disabled="busy" /></label
                ><label
                  >音高下限（Hz）<input
                    v-model.number="floor"
                    type="number"
                    min="50"
                    max="999"
                    :disabled="busy" /></label
                ><label
                  >音高上限（Hz）<input
                    v-model.number="ceiling"
                    type="number"
                    min="51"
                    max="1000"
                    :disabled="busy"
                /></label>
              </div>
              <button class="text-button" @click="playSelection">▷ 回听所选片段</button
              ><label class="reference-select"
                >本次参照<select v-model="referenceId" :disabled="busy">
                  <option value="builtin">内置合成示范</option>
                  <option value="none">只分析本人录音</option>
                  <option v-for="p in personalReferences" :key="p.id" :value="p.id">
                    个人参照 · {{ new Date(p.created_at * 1000).toLocaleString() }}
                  </option>
                </select></label
              >
            </details>
            <label class="confirm-recording"
              ><input
                v-model="confirmed"
                type="checkbox"
                :disabled="busy"
              />我已回听，确认读的是当前题目。</label
            ><button class="primary submit" :disabled="!confirmed || locked" @click="submit">
              {{ busy ? `正在分析 · ${waited}s` : '分析这次录音 →' }}
            </button>
          </div>
        </section>

        <AgentWorkflow :trace="trace" :busy="busy" />
        <div v-if="busy" class="waiting-message" role="status">
          后台正在执行真实分析，已等待 {{ waited }} 秒。刷新后可恢复任务。
        </div>
        <section v-if="current?.status === 'failed'" class="evidence-panel">
          <h3>原录音仍然保留</h3>
          <p>{{ current.error }}</p>
          <audio :src="current.audio_url" controls preload="none" aria-label="失败练习原录音" />
          <button class="secondary" :disabled="locked" @click="restoreRecording">
            载入原录音重新分析
          </button>
        </section>
        <template v-if="result && current">
          <section
            v-if="result.alignment && result.alignment.status !== 'aligned'"
            class="alignment-warning"
            role="status"
          >
            <strong>声学图表已保留 · 专项判断受限</strong>
            <p>{{ result.alignment.message }}</p>
          </section>
          <section class="result-overview">
            <div class="section-title">
              <div>
                <span class="section-label">YOUR PRACTICE</span>
                <h3>这一遍的练习反馈</h3>
              </div>
              <button class="text-button" @click="exportData">导出声学 CSV ↗</button>
            </div>
            <div class="metric-grid">
              <article v-for="metric in result.metrics" :key="metric.code">
                <span>{{ metric.label }}</span
                ><strong
                  >{{ metric.value ?? '—' }} <small>{{ metric.unit }}</small></strong
                ><span :class="['assessment', metric.state]">{{ statusLabels[metric.state] }}</span>
              </article>
              <article>
                <span>实际选区时长</span
                ><strong
                  >{{ (result.selection.end_s - result.selection.start_s).toFixed(2) }}
                  <small>秒</small></strong
                ><span class="quiet">保留真实时间，不随曲线缩放</span>
              </article>
              <article>
                <span>相对音域跨度</span
                ><strong>{{ result.features.pitch_range_st }} <small>半音</small></strong
                ><span class="quiet">本次有效音高的 P10–P90</span>
              </article>
            </div>
            <div class="result-playback">
              <label
                >你的录音<audio
                  ref="learnerAudio"
                  :src="current.audio_url"
                  controls
                  preload="metadata" /></label
              ><label v-if="result.reference"
                >{{ result.reference.label
                }}<audio :src="result.reference.audio_url" controls preload="none"
              /></label>
            </div>
            <button
              class="text-button"
              :disabled="result.alignment?.status === 'unavailable'"
              @click="makeReference"
            >
              将这次录音设为个人参照
            </button>
          </section>
          <section class="comparison-picker">
            <label
              >与前一次复练对比<select v-model="comparisonId">
                <option value="">显示本次示范参照</option>
                <option v-for="p in comparable" :key="p.id" :value="p.id">
                  {{ new Date(p.created_at * 1000).toLocaleString() }}
                </option>
              </select></label
            >
            <p>同题目、参照版本和音高参数一致时可直接比较。</p>
            <audio
              v-if="comparison"
              :src="comparison.audio_url"
              controls
              aria-label="历史复练录音"
            />
          </section>
          <ProsodyChart
            :result="result"
            :comparison="comparison?.result"
            :comparison-label="comparison ? '历史复练录音' : undefined"
            @seek="seek"
          />
          <PronunciationDashboard
            :key="current.id"
            :result="result"
            :practice="current"
            :history="history"
            :previous="comparison?.result"
            :tip="selected?.tip || ''"
          />
          <section v-if="result.reference" class="syllable-panel">
            <div class="section-title">
              <h3>听听语调调整后的自己</h3>
              <button
                class="secondary"
                :disabled="altering || result.quality.octave_jumps > 0 || !result.words.length"
                @click="alteredSample"
              >
                {{ altering ? '正在生成…' : '生成语调调整试听' }}
              </button>
            </div>
            <p class="quiet">
              使用本人录音，按参照调整音高。原节奏、发音动作和音量保持原样，作为教学试听。
              <span v-if="!result.words.length"
                >请先取得词语定位，才能生成对应片段的语调试听。</span
              >
            </p>
            <audio
              v-if="alteredUrl"
              :src="alteredUrl"
              controls
              style="width: 100%"
              aria-label="语调调整教学试听"
            />
          </section>
          <section v-if="result.syllables.length" class="syllable-panel">
            <h3>音节线索对照</h3>
            <div class="syllable-grid">
              <button
                v-for="(syllable, index) in result.syllables"
                :key="index"
                @click="seek(syllable.start_s, syllable.end_s)"
              >
                <strong>{{ syllable.label }}</strong
                ><span>元音时长 {{ syllable.duration_s }}s</span
                ><span>相对音量 {{ syllable.energy_dbfs }} dBFS</span
                ><i :style="{ width: `${Math.min(100, syllable.duration_s * 300)}%` }" />
              </button>
            </div>
            <p class="quiet">显示元音核的近似定位与测量，点击可回听。</p>
          </section>
          <section class="evidence-panel">
            <h3>把建议落到具体片段</h3>
            <article v-for="(finding, i) in result.findings" :key="i">
              <button class="play-clip" @click="seek(finding.start_s, finding.end_s)">
                ▷ {{ finding.start_s.toFixed(2) }}–{{ finding.end_s.toFixed(2) }}s
              </button>
              <div>
                <p>{{ finding.evidence }}</p>
                <strong>下一遍：{{ finding.suggestion }}</strong>
              </div>
            </article>
            <details>
              <summary>录音质量与分析说明</summary>
              <p v-for="warning in result.quality.warnings" :key="warning">{{ warning }}</p>
              <p>这些结果用于专项复练，不等同于音素准确率或 CET 考试成绩。</p>
            </details>
          </section>
          <section class="coach-panel">
            <div class="section-title">
              <div>
                <span class="section-label">PERSONAL COACH</span>
                <h3>把这一次，练明白</h3>
              </div>
              <select v-model="coachModel" aria-label="教学模型" :disabled="coachBusy">
                <option value="deepseek-flash">DeepSeek Flash</option>
                <option value="deepseek-v4-pro">DeepSeek V4 Pro</option>
              </select>
            </div>
            <p>教学智能体结合本次实测和你开启的练习记忆，给出下一轮动作。</p>
            <div class="coach-input">
              <input
                v-model="coachQuestion"
                aria-label="发音练习问题"
                placeholder="例如：这个重音该怎么练？ / Explain in English"
                maxlength="1000"
                :disabled="coachBusy"
                @keydown.enter="askCoach"
              /><button class="primary" :disabled="coachBusy" @click="askCoach">
                {{ coachBusy ? '正在解读…' : '生成练习建议' }}
              </button>
            </div>
            <div v-if="coachAnswer" class="coach-answer">
              <span>{{ coachSource }}</span>
              <p>{{ coachAnswer }}</p>
            </div>
          </section>
          <AgentWorkflow
            v-if="coachTrace.length || coachBusy"
            :trace="coachTrace"
            :busy="coachBusy"
            teaching
          />
        </template>
        <div v-else-if="tab === 'compare'" class="empty-state">
          <span>↔</span>
          <h3>从一次完整练习开始</h3>
          <p>完成分析后，可以对比示范与自己前后两次的变化。</p>
          <button class="secondary" @click="tab = 'practice'">开始专项训练</button>
        </div>
      </div>
    </div>

    <section v-else class="history-panel">
      <div class="section-title">
        <div>
          <h2>每一遍，都留下依据</h2>
          <p>当前浏览器的独立练习记录；录音保留期为 30 天，服务启动时清理到期记录。</p>
        </div>
        <button class="secondary" @click="refresh">刷新记录</button>
      </div>
      <div v-if="!history.length" class="empty-state">
        <span>◷</span>
        <h3>还没有练习记录</h3>
        <p>选一道短句，开始第一遍。</p>
        <button class="primary" @click="tab = 'practice'">去练习</button>
      </div>
      <article v-for="item in history" :key="item.id" class="history-item">
        <div>
          <span class="section-label">{{ new Date(item.created_at * 1000).toLocaleString() }}</span>
          <h3>{{ exercises.find((e) => e.id === item.exercise_id)?.title || item.exercise_id }}</h3>
          <span class="quiet"
            >{{ item.is_reference ? '个人参照 · ' : ''
            }}{{
              item.status === 'completed'
                ? '分析已完成'
                : item.status === 'failed'
                  ? item.error
                  : '分析中'
            }}</span
          >
        </div>
        <div class="history-actions">
          <button class="secondary" :disabled="locked" @click="openPractice(item)">查看练习</button
          ><button
            class="text-button danger"
            :disabled="locked || ['queued', 'processing'].includes(item.status)"
            @click="removePractice(item)"
          >
            删除
          </button>
        </div>
      </article>
    </section>
    <footer>ENGLISH PRONUNCIATION LAB <span>听见变化，练得具体。</span></footer>
  </main>
</template>

<style scoped>
.alignment-warning {
  padding: 18px 22px;
  border: 1px solid #d69a3a;
  border-radius: 14px;
  background: #d69a3a0d;
  font-size: 13px;
  line-height: 1.9;
}
.alignment-warning strong {
  color: #a56c15;
}
.pronunciation-page {
  max-width: 1280px;
  margin: auto;
  padding: 42px 32px 24px;
  color: var(--cet-text);
  font-family: Inter, 'Segoe UI', 'Microsoft YaHei', sans-serif;
}
.page-heading {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 20px;
}
.eyebrow,
.section-label {
  font-size: 10px;
  font-weight: 650;
  letter-spacing: 2px;
  color: var(--cet-muted);
}
.eyebrow {
  color: #3770bd;
  margin: 0 0 14px;
}
h1 {
  font-size: 34px;
  letter-spacing: -1px;
  margin: 0;
  font-weight: 700;
}
h1 span {
  display: block;
  font-size: 14px;
  letter-spacing: 0;
  font-weight: 400;
  color: var(--cet-muted);
  margin-top: 12px;
}
.intro {
  font-size: 13px;
  color: var(--cet-muted);
  margin-top: 12px;
}
.service-status {
  font-size: 11px;
  white-space: nowrap;
  color: #267255;
  padding: 10px 14px;
  border: 1px solid #26725533;
  background: #26725508;
  border-radius: 30px;
}
.service-status i {
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #39a378;
  margin-right: 8px;
}
.service-status.offline {
  color: #9e6419;
}
.service-status.offline i {
  background: #c68b3c;
}
.page-tabs {
  display: flex;
  border-bottom: 1px solid var(--cet-line);
  gap: 25px;
  margin: 27px 0 28px;
}
.page-tabs button {
  border: 0;
  border-bottom: 2px solid transparent;
  padding: 13px 3px;
  background: transparent;
  color: var(--cet-muted);
  font: inherit;
  font-size: 13px;
  cursor: pointer;
}
.page-tabs button[aria-selected='true'] {
  border-color: #2563eb;
  color: #2563eb;
  font-weight: 650;
}
.page-tabs span {
  font-size: 10px;
  padding: 2px 6px;
  background: var(--cet-surface-2);
  margin-left: 6px;
  border-radius: 4px;
}
.training-layout {
  display: grid;
  grid-template-columns: 220px minmax(0, 1fr);
  gap: 28px;
}
.training-sidebar > .section-label {
  display: block;
  margin: 6px 0 17px;
}
.category-button {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 11px;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 12px;
  padding: 15px 11px;
  margin-bottom: 6px;
  text-align: left;
  color: var(--cet-text);
  cursor: pointer;
}
.category-button.selected {
  background: #2563eb0d;
  border-color: #2563eb26;
}
.category-icon {
  width: 34px;
  height: 34px;
  border-radius: 9px;
  display: grid;
  place-items: center;
  background: var(--cet-surface);
  font-size: 19px;
  color: var(--cet-muted);
}
.selected .category-icon {
  background: #2563eb;
  color: white;
}
.category-button strong {
  font-size: 13px;
  display: block;
}
.category-button small {
  display: block;
  font-size: 8px;
  letter-spacing: 1px;
  margin-top: 5px;
  color: var(--cet-muted);
}
.category-arrow {
  margin-left: auto;
  color: var(--cet-muted);
}
.sidebar-tip {
  margin-top: 26px;
  border-top: 1px solid var(--cet-line);
  padding: 20px 8px;
}
.sidebar-tip span {
  font-size: 12px;
  font-weight: 650;
}
.sidebar-tip p,
.memory-card p {
  font-size: 12px;
  line-height: 1.9;
  color: var(--cet-muted);
}
.memory-card {
  padding: 18px 14px;
  background: var(--cet-surface);
  border: 1px solid var(--cet-line);
  border-radius: 12px;
  margin-top: 5px;
}
.memory-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  font-size: 12px;
}
.memory-head input {
  accent-color: #2563eb;
  width: 16px;
  height: 16px;
}
.memory-card .text-button {
  padding: 0;
  font-size: 11px;
}
.training-content {
  display: flex;
  flex-direction: column;
  gap: 21px;
  min-width: 0;
}
.practice-card,
.record-card,
.result-overview,
.coach-panel,
.evidence-panel,
.syllable-panel,
.comparison-picker,
.history-panel {
  background: var(--cet-surface);
  border: 1px solid var(--cet-line);
  border-radius: 18px;
  padding: 26px;
}
.practice-card {
  background: linear-gradient(120deg, var(--cet-surface), #2563eb05);
}
.card-topline {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.exercise-badge {
  font-size: 10px;
  color: #3163a8;
  background: #2563eb10;
  border: 1px solid #2563eb1b;
  padding: 5px 9px;
  border-radius: 5px;
}
.quiet {
  font-size: 11px;
  color: var(--cet-muted);
  line-height: 1.7;
}
.exercise-options {
  display: flex;
  gap: 7px;
  flex-wrap: wrap;
  margin: 21px 0;
}
.exercise-options button {
  padding: 7px 11px;
  background: transparent;
  border: 1px solid var(--cet-line);
  border-radius: 7px;
  font: inherit;
  font-size: 11px;
  color: var(--cet-muted);
  cursor: pointer;
}
.exercise-options button.active {
  border-color: #2563eb;
  color: #2563eb;
  background: #2563eb08;
}
.exercise-context {
  font-size: 12px;
  line-height: 1.8;
  color: var(--cet-muted);
  margin: 21px 0 10px;
}
.practice-card h2 {
  font-size: clamp(25px, 3vw, 41px);
  letter-spacing: -0.5px;
  line-height: 1.45;
  font-weight: 600;
  margin: 12px 0;
}
.exercise-tip {
  font-size: 12px;
  color: var(--cet-muted);
  line-height: 1.9;
}
.reference-controls {
  margin-top: 22px;
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.reference-controls audio {
  width: 265px;
  height: 36px;
}
.section-title {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}
.section-title h3,
.evidence-panel h3,
.syllable-panel h3 {
  margin: 3px 0 8px;
  font-size: 17px;
}
.section-title p,
.coach-panel > p,
.comparison-picker p {
  font-size: 12px;
  color: var(--cet-muted);
  line-height: 1.8;
  margin: 7px 0;
}
.record-time {
  font-variant-numeric: tabular-nums;
  font-size: 23px;
  color: var(--cet-text);
}
.record-time small {
  font-size: 11px;
  color: var(--cet-muted);
}
.record-center {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 24px 0 13px;
  gap: 15px;
}
.microphone-orbit {
  height: 110px;
  width: 110px;
  border: 1px solid #2563eb13;
  border-radius: 50%;
  display: grid;
  place-items: center;
  background: #2563eb03;
}
.mic-button {
  height: 76px;
  width: 76px;
  border-radius: 50%;
  border: 0;
  background: #2563eb;
  color: white;
  cursor: pointer;
  display: grid;
  place-items: center;
  box-shadow: 0 7px 20px #2563eb22;
}
.mic-button:hover {
  background: #1d4ed8;
}
.mic-button.stop {
  background: #cc4f4f;
  font-size: 24px;
}
.recording {
  box-shadow: 0 0 0 11px #cc4f4f0a;
}
.record-center > strong {
  font-size: 13px;
  font-weight: 500;
}
.level-meter {
  width: 110px;
  height: 4px;
  border-radius: 6px;
  overflow: hidden;
  background: var(--cet-surface-2);
}
.level-meter i {
  display: block;
  background: #2563eb;
  height: 100%;
  transition: width 0.1s;
}
.upload-button {
  font-size: 11px;
  color: var(--cet-muted);
  text-decoration: underline;
  text-underline-offset: 4px;
  cursor: pointer;
  margin-top: 5px;
}
.upload-button input {
  position: absolute;
  width: 1px;
  height: 1px;
  opacity: 0;
}
.disabled {
  opacity: 0.4;
  pointer-events: none;
}
.preview {
  margin-top: 20px;
  border-top: 1px solid var(--cet-line);
  padding-top: 21px;
}
.preview-heading {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  gap: 10px;
}
.preview-heading a {
  color: #2563eb;
  font-size: 11px;
}
.preview audio {
  width: 100%;
  height: 42px;
  margin: 13px 0;
}
summary {
  font-size: 12px;
  cursor: pointer;
  color: var(--cet-muted);
  padding: 8px 0;
}
details {
  font-size: 12px;
  line-height: 1.9;
}
.options-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 13px;
  margin: 13px 0;
}
.options-grid label,
.reference-select {
  display: flex;
  flex-direction: column;
  gap: 7px;
  font-size: 11px;
  color: var(--cet-muted);
}
input:not([type='checkbox']):not([type='file']),
select {
  font: inherit;
  font-size: 12px;
  border: 1px solid var(--cet-line);
  background: var(--cet-surface);
  color: var(--cet-text);
  padding: 10px 12px;
  border-radius: 8px;
  min-width: 0;
  max-width: 100%;
}
input:focus,
select:focus,
button:focus-visible {
  outline: 2px solid #2563eb;
  outline-offset: 3px;
}
.reference-select {
  margin: 13px 0;
}
.confirm-recording {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 12px;
  margin: 20px 0 14px;
  color: var(--cet-muted);
}
input[type='checkbox'] {
  accent-color: #2563eb;
}
.primary,
.secondary {
  font: inherit;
  font-size: 12px;
  padding: 11px 17px;
  border-radius: 8px;
  cursor: pointer;
}
.primary {
  border: 1px solid #2563eb;
  background: #2563eb;
  color: white;
}
.primary:hover {
  background: #1d4ed8;
}
.secondary {
  border: 1px solid var(--cet-line);
  background: var(--cet-surface);
  color: var(--cet-text);
}
button:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.submit {
  width: 100%;
  padding: 13px;
}
.text-button {
  font: inherit;
  font-size: 12px;
  border: 0;
  background: transparent;
  color: #3871bd;
  padding: 8px;
  cursor: pointer;
}
.message {
  border-radius: 10px;
  padding: 13px 16px;
  font-size: 13px;
  line-height: 1.8;
  margin-bottom: 18px;
}
.message.error {
  background: #fff0ef;
  color: #9b3028;
  border: 1px solid #e09c96;
}
.message.notice {
  background: #edf4fc;
  color: #285987;
  border: 1px solid #bed4ee;
}
.waiting-message {
  font-size: 12px;
  color: var(--cet-muted);
  text-align: center;
}
.metric-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 13px;
  margin-top: 20px;
}
.metric-grid article {
  padding: 17px 13px;
  background: var(--cet-surface-2);
  border-radius: 11px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.metric-grid article > span:first-child {
  font-size: 11px;
  color: var(--cet-muted);
}
.metric-grid article > strong {
  font-size: 25px;
  font-weight: 600;
}
.metric-grid article small {
  font-size: 11px;
  font-weight: 400;
  color: var(--cet-muted);
}
.assessment {
  font-size: 10px;
  color: #285987;
}
.assessment.matched {
  color: #267255;
}
.assessment.adjust {
  color: #ac672d;
}
.assessment.uncertain {
  color: var(--cet-muted);
}
.result-playback {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
  margin: 22px 0 5px;
}
.result-playback label {
  font-size: 11px;
  color: var(--cet-muted);
}
.result-playback audio {
  width: 100%;
  margin-top: 10px;
  height: 40px;
}
.comparison-picker label {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  font-size: 12px;
}
.comparison-picker select {
  max-width: 65%;
}
.comparison-picker audio {
  width: 100%;
  height: 36px;
  margin-top: 8px;
}
.syllable-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin-top: 20px;
}
.syllable-grid button {
  padding: 15px;
  text-align: left;
  background: var(--cet-surface-2);
  border: 1px solid var(--cet-line);
  border-radius: 10px;
  cursor: pointer;
  color: var(--cet-text);
}
.syllable-grid strong {
  font-size: 19px;
}
.syllable-grid span {
  display: block;
  font-size: 11px;
  margin-top: 8px;
  color: var(--cet-muted);
}
.syllable-grid i {
  display: block;
  height: 4px;
  background: #2563eb;
  border-radius: 3px;
  margin-top: 16px;
}
.evidence-panel article {
  display: flex;
  gap: 16px;
  align-items: flex-start;
  padding: 18px 0;
}
.play-clip {
  font-size: 11px;
  white-space: nowrap;
  color: #2563eb;
  background: #2563eb0a;
  border: 1px solid #2563eb33;
  border-radius: 7px;
  padding: 9px 10px;
  cursor: pointer;
}
.evidence-panel article p {
  font-size: 13px;
  line-height: 1.9;
  margin: 0 0 10px;
}
.evidence-panel article strong {
  font-size: 12px;
  font-weight: 500;
  line-height: 1.9;
}
.coach-input {
  display: flex;
  gap: 10px;
  margin-top: 19px;
}
.coach-input input {
  flex: 1;
  min-width: 0;
}
.coach-input button {
  white-space: nowrap;
}
.coach-answer {
  margin-top: 20px;
  border-top: 1px solid var(--cet-line);
  padding-top: 17px;
}
.coach-answer > span {
  font-size: 10px;
  color: #3871bd;
}
.coach-answer p {
  white-space: pre-wrap;
  line-height: 1.9;
  font-size: 13px;
}
.empty-state {
  text-align: center;
  padding: 50px 20px;
  border: 1px dashed var(--cet-line);
  border-radius: 15px;
}
.empty-state > span {
  font-size: 34px;
  color: #87a5cc;
}
.empty-state h3 {
  font-size: 18px;
}
.empty-state p {
  font-size: 13px;
  line-height: 1.8;
  color: var(--cet-muted);
  margin-bottom: 25px;
}
.history-panel h2 {
  font-size: 22px;
  margin: 0;
}
.history-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 20px;
  padding: 24px 0;
  border-bottom: 1px solid var(--cet-line);
}
.history-item h3 {
  font-size: 16px;
  margin: 10px 0;
}
.history-item .section-label {
  font-size: 10px;
  letter-spacing: 0.2px;
}
.history-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}
.danger {
  color: #af4747;
}
footer {
  display: flex;
  justify-content: space-between;
  border-top: 1px solid var(--cet-line);
  margin-top: 45px;
  padding: 24px 0 0;
  font-size: 9px;
  letter-spacing: 2px;
  color: var(--cet-muted);
}
footer span {
  letter-spacing: 1px;
  font-size: 10px;
}
@media (max-width: 900px) {
  .pronunciation-page {
    padding: 28px 20px;
  }
  .training-layout {
    grid-template-columns: 180px minmax(0, 1fr);
    gap: 20px;
  }
  .service-status {
    font-size: 10px;
  }
  .options-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .metric-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .metric-grid article:last-child {
    grid-column: 1/-1;
  }
  .result-playback {
    grid-template-columns: 1fr;
  }
}
@media (max-width: 650px) {
  .pronunciation-page {
    padding: 23px 14px;
  }
  .page-heading {
    align-items: flex-start;
    flex-direction: column;
    gap: 10px;
  }
  h1 {
    font-size: 28px;
  }
  h1 span {
    font-size: 12px;
  }
  .intro {
    display: none;
  }
  .service-status {
    padding: 7px 10px;
  }
  .page-tabs {
    margin: 20px 0;
  }
  .training-layout {
    display: block;
  }
  .training-sidebar {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 5px;
    margin-bottom: 17px;
  }
  .training-sidebar > .section-label {
    display: none;
  }
  .category-button {
    padding: 10px 7px;
    gap: 8px;
  }
  .category-button small {
    font-size: 7px;
    letter-spacing: 0.5px;
  }
  .category-button strong {
    font-size: 12px;
  }
  .category-icon {
    width: 28px;
    height: 28px;
    font-size: 17px;
  }
  .sidebar-tip {
    display: none;
  }
  .memory-card {
    grid-column: 1/-1;
    padding: 12px;
    margin: 8px 0;
  }
  .memory-card p {
    margin: 6px 0;
  }
  .practice-card,
  .record-card,
  .result-overview,
  .coach-panel,
  .evidence-panel,
  .syllable-panel,
  .comparison-picker,
  .history-panel {
    padding: 19px 16px;
    border-radius: 15px;
  }
  .training-content {
    gap: 16px;
  }
  .reference-controls audio {
    width: 100%;
  }
  .exercise-options {
    gap: 5px;
  }
  .exercise-options button {
    font-size: 10px;
    padding: 6px 8px;
  }
  .section-title {
    flex-wrap: wrap;
  }
  .metric-grid {
    gap: 9px;
  }
  .metric-grid article {
    padding: 14px 10px;
  }
  .metric-grid article > strong {
    font-size: 22px;
  }
  .comparison-picker label {
    display: block;
  }
  .comparison-picker select {
    max-width: 100%;
    width: 100%;
    margin-top: 10px;
  }
  .evidence-panel article {
    display: block;
  }
  .evidence-panel article p {
    margin-top: 13px;
  }
  .coach-input {
    flex-direction: column;
  }
  .history-item {
    align-items: flex-start;
    flex-direction: column;
    gap: 13px;
  }
  .history-actions {
    width: 100%;
    justify-content: flex-end;
  }
  .preview-heading {
    font-size: 11px;
  }
  .preview-heading strong {
    overflow-wrap: anywhere;
  }
  .page-tabs {
    gap: 20px;
  }
  footer {
    letter-spacing: 1px;
    font-size: 8px;
  }
  .section-title h3,
  .evidence-panel h3 {
    font-size: 16px;
  }
}
</style>
