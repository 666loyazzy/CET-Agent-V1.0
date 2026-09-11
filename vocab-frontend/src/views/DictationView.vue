<script setup lang="ts">
import { onMounted, onUnmounted, reactive, ref, nextTick, computed } from 'vue'
import TopNav from '@/components/TopNav.vue'
import { submitReviewByEn, setReviewFlag } from '@/api/vocab'

type Direction = 'en_to_zh' | 'zh_to_en'
type Status = 'loading' | 'question' | 'judging' | 'result' | 'done'
type Mode = 'en_to_zh' | 'zh_to_en_hint' | 'zh_to_en_full' | 'mixed'

const MODE_LABELS: Record<Mode, string> = {
  en_to_zh: '英→中',
  zh_to_en_hint: '中→英 · 提示',
  zh_to_en_full: '中→英',
  mixed: '混合',
}

interface Question {
  en: string
  zh: string        // short (first meaning) — used for display
  zhFull: string    // raw multi-POS string from wordlist — used for local match
  direction: Direction
  hintMode: boolean
  hintPrefix: string
}

interface JudgeResult {
  correct: boolean
  reason: string
  correctAnswer: string
}

const state = reactive({
  status: 'loading' as Status,
  level: 'CET-4' as 'CET-4' | 'CET-6',
  mode: 'zh_to_en_hint' as Mode,
  words: [] as { en: string; zh: string; zhFull: string }[],
  cursor: 0,
  sessionSize: 20,
  q: null as Question | null,
  userAnswer: '',
  result: null as JudgeResult | null,
  right: 0,
  total: 0,
  errorMsg: '',
})

const inputRef = ref<HTMLInputElement | null>(null)

const displayPrompt = computed(() => {
  if (!state.q) return ''
  return state.q.direction === 'en_to_zh' ? state.q.en : state.q.zh
})

const directionLabel = computed(() => {
  if (!state.q) return ''
  return state.q.direction === 'en_to_zh' ? '英 → 中' : '中 → 英'
})

const inputPlaceholder = computed(() => {
  if (!state.q) return ''
  if (state.q.direction === 'en_to_zh') return '输入中文释义…'
  return state.q.hintMode ? '补全后面的字母…' : '输入英文单词…'
})

const scoreText = computed(() => `${state.right} / ${state.total}`)

function parseWordlist(text: string): { en: string; zh: string; zhFull: string }[] {
  const posRe = /^(?:n|v|adj|adv|prep|pron|conj|art)\.\s*/i
  const cutRe = /^([^，,；;]+?)(?=\s+(?:n|v|adj|adv|prep|pron|conj|art)\.|[，,；;]|$)/
  const out: { en: string; zh: string; zhFull: string }[] = []
  for (const line of text.split(/\r?\n/)) {
    const idx = line.indexOf('\t')
    if (idx < 1) continue
    const en = line.slice(0, idx).trim()
    const rawZh = line.slice(idx + 1).trim()
    if (!en || !rawZh) continue
    const cleaned = rawZh.replace(posRe, '').trim()
    const m = cleaned.match(cutRe)
    const zh = (m ? m[1] : cleaned).trim()
    if (zh) out.push({ en, zh, zhFull: rawZh })
  }
  return out
}

function shuffle<T>(arr: T[]): T[] {
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1))
    ;[arr[i], arr[j]] = [arr[j], arr[i]]
  }
  return arr
}

async function loadWords() {
  state.status = 'loading'
  state.errorMsg = ''
  const file = state.level === 'CET-6' ? 'words-cet6.txt' : 'words-cet4.txt'
  try {
    const res = await fetch(`/static/${file}`)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const words = parseWordlist(await res.text())
    if (!words.length) throw new Error('词库为空')
    state.words = shuffle(words).slice(0, state.sessionSize)
    state.cursor = 0
    state.right = 0
    state.total = 0
    buildQuestion()
  } catch (e: any) {
    state.errorMsg = `加载词库失败: ${e.message || e}`
    state.status = 'question'
  }
}

function pickShape(): { direction: Direction; wantsHint: boolean } {
  const m = state.mode
  if (m === 'en_to_zh') return { direction: 'en_to_zh', wantsHint: false }
  if (m === 'zh_to_en_hint') return { direction: 'zh_to_en', wantsHint: true }
  if (m === 'zh_to_en_full') return { direction: 'zh_to_en', wantsHint: false }
  // mixed: uniform across the three primary shapes
  const r = Math.random()
  if (r < 1 / 3) return { direction: 'en_to_zh', wantsHint: false }
  if (r < 2 / 3) return { direction: 'zh_to_en', wantsHint: true }
  return { direction: 'zh_to_en', wantsHint: false }
}

function buildQuestion() {
  if (state.cursor >= state.words.length) {
    state.status = 'done'
    return
  }
  const { en, zh, zhFull } = state.words[state.cursor]
  const { direction, wantsHint } = pickShape()
  let hintMode = false
  let hintPrefix = ''
  if (direction === 'zh_to_en' && wantsHint && en.length >= 3) {
    hintMode = true
    hintPrefix = en.slice(0, en.length >= 4 ? 2 : 1).toLowerCase()
  }
  state.q = { en, zh, zhFull, direction, hintMode, hintPrefix }
  state.userAnswer = ''
  state.result = null
  state.status = 'question'
  mastered.value = false
  nextTick(() => inputRef.value?.focus())
}

async function submit() {
  if (state.status !== 'question' || !state.q) return
  const q = state.q
  const raw = state.userAnswer.trim()
  if (!raw) return
  state.total++
  // Hint mode: local exact check on the completion (case-insensitive).
  if (q.hintMode) {
    const full = (q.hintPrefix + raw).toLowerCase()
    const target = q.en.toLowerCase()
    const correct = full === target
    if (correct) state.right++
    state.result = {
      correct,
      reason: correct ? '拼写正确' : `应为 ${q.en.slice(q.hintPrefix.length)}`,
      correctAnswer: q.en,
    }
    state.status = 'result'
    recordReview(q.en, correct)
    return
  }
  // AI judgment path.
  state.status = 'judging'
  try {
    const res = await fetch('/api/vocab/judge', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        direction: q.direction,
        reference_en: q.en,
        reference_zh: q.zh,
        reference_zh_full: q.zhFull,
        answer: raw,
      }),
    })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const data = await res.json()
    if (data.correct) state.right++
    state.result = {
      correct: !!data.correct,
      reason: data.reason || (data.correct ? '正确' : '不正确'),
      correctAnswer: data.correct_answer,
    }
    recordReview(q.en, !!data.correct)
  } catch (e: any) {
    state.result = {
      correct: false,
      reason: `判分失败: ${e.message || e}`,
      correctAnswer: q.direction === 'en_to_zh' ? q.zh : q.en,
    }
    // Judgment failed — don't record a review; the answer's correctness
    // is unknown and a false "wrong" would poison the ebbinghaus schedule.
  }
  state.status = 'result'
}

function recordReview(en: string, correct: boolean) {
  const book = state.level === 'CET-6' ? 'cet6' : 'cet4'
  submitReviewByEn(book, en, correct).catch((e) => {
    console.warn('[dictation] recordReview failed:', e)
  })
}

const mastered = ref(false)

async function markMastered() {
  if (!state.q || mastered.value) return
  const book = state.level === 'CET-6' ? 'cet6' : 'cet4'
  try {
    await setReviewFlag({ book, en: state.q.en, flag: 2 })
    mastered.value = true
  } catch (e) {
    console.warn('[dictation] markMastered failed:', e)
  }
}

function next() {
  state.cursor++
  buildQuestion()
}

function restart() {
  loadWords()
}

function onLevelChange(lv: 'CET-4' | 'CET-6') {
  if (state.level === lv) return
  state.level = lv
  loadWords()
}

function setMode(m: Mode) {
  if (state.mode === m) return
  state.mode = m
  localStorage.setItem('cet-agent-dictation-mode', m)
  loadWords()
}

const MODES: Mode[] = ['en_to_zh', 'zh_to_en_hint', 'zh_to_en_full', 'mixed']
function modeLabel(m: Mode): string { return MODE_LABELS[m] }

function onKey(e: KeyboardEvent) {
  if (state.status === 'result' && (e.key === 'Enter' || e.key === ' ')) {
    e.preventDefault()
    next()
  }
}

onMounted(() => {
  const saved = localStorage.getItem('cet-agent-level')
  if (saved === 'CET-6' || saved === 'CET-4') state.level = saved
  const savedMode = localStorage.getItem('cet-agent-dictation-mode') as Mode | null
  if (savedMode && (MODES as string[]).includes(savedMode)) state.mode = savedMode
  window.addEventListener('keydown', onKey)
  loadWords()
})

onUnmounted(() => {
  window.removeEventListener('keydown', onKey)
})
</script>

<template>
  <TopNav active="dictation" @level-change="onLevelChange" />
  <main class="dictation">
    <div class="dict-subbar">
      <div class="dict-title">默写 · {{ state.level }}</div>
      <div class="dict-stats">
        <span class="stat"><span class="label">得分</span> {{ scoreText }}</span>
        <span class="stat"><span class="label">进度</span> {{ Math.min(state.cursor + 1, state.sessionSize) }} / {{ state.sessionSize }}</span>
      </div>
    </div>
    <div class="mode-picker">
      <span class="mode-label">题型</span>
      <div class="mode-btns">
        <button
          v-for="m in MODES"
          :key="m"
          class="mode-btn"
          :class="{ active: state.mode === m }"
          @click="setMode(m)"
          type="button"
        >{{ modeLabel(m) }}</button>
      </div>
    </div>

    <section class="card">
      <div v-if="state.errorMsg" class="error">{{ state.errorMsg }}</div>

      <template v-if="state.status === 'loading'">
        <div class="loading">加载词库中…</div>
      </template>

      <template v-else-if="state.status === 'done'">
        <h2 class="done-title">这一组做完了</h2>
        <p class="done-score">得分 {{ scoreText }}（正确率 {{ Math.round((state.right / Math.max(state.total, 1)) * 100) }}%）</p>
        <button class="btn primary" @click="restart">再来一组</button>
      </template>

      <template v-else>
        <div class="direction">{{ directionLabel }}<span v-if="state.q?.hintMode" class="hint-tag">提示模式</span></div>
        <div class="prompt">{{ displayPrompt }}</div>

        <div class="answer-row">
          <span v-if="state.q?.hintMode" class="hint-prefix">{{ state.q.hintPrefix }}</span>
          <input
            ref="inputRef"
            v-model="state.userAnswer"
            :placeholder="inputPlaceholder"
            :disabled="state.status !== 'question'"
            @keydown.enter="submit"
            autocomplete="off"
            autocapitalize="off"
            spellcheck="false"
          />
        </div>

        <div class="actions">
          <button
            class="btn primary"
            :disabled="state.status !== 'question' || !state.userAnswer.trim()"
            @click="submit"
          >
            {{ state.status === 'judging' ? '判分中…' : '提交（回车）' }}
          </button>
        </div>

        <div v-if="state.status === 'result' && state.result" class="verdict" :class="{ ok: state.result.correct, bad: !state.result.correct }">
          <div class="verdict-icon">{{ state.result.correct ? '✓ 正确' : '✗ 错误' }}</div>
          <div class="verdict-reason">{{ state.result.reason }}</div>
          <div class="verdict-answer">
            <span class="label">正确答案：</span>
            <span class="value">{{ state.result.correctAnswer }}</span>
          </div>
          <div class="verdict-actions">
            <button class="btn secondary" @click="next">下一题（回车/空格）</button>
            <button class="btn ghost" @click="markMastered" :disabled="mastered">
              {{ mastered ? '✓ 已标记' : '标记为已掌握' }}
            </button>
          </div>
        </div>
      </template>
    </section>
  </main>
</template>

<style scoped>
.dictation {
  min-height: calc(100vh - var(--cet-nav-h, 52px));
  background: var(--cet-body-bg);
  color: var(--cet-text);
  padding: 16px 24px 40px;
  font-family: var(--cet-font);
}

.dict-subbar {
  max-width: 640px;
  margin: 0 auto 20px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}
.dict-title {
  color: var(--cet-brand);
  font-size: 14px;
  font-weight: 600;
  letter-spacing: 0.02em;
}
.dict-stats { display: flex; gap: 18px; }
.stat { font-size: 12px; color: var(--cet-text); }
.stat .label { color: var(--cet-muted); margin-right: 4px; }

.mode-picker {
  max-width: 640px;
  margin: 0 auto 18px;
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.mode-label {
  font-size: 12px;
  color: var(--cet-muted);
  letter-spacing: 0.02em;
}
.mode-btns {
  display: inline-flex;
  background: var(--cet-surface);
  border: 1px solid var(--cet-line);
  border-radius: 8px;
  overflow: hidden;
}
.mode-btn {
  background: transparent;
  color: var(--cet-muted);
  border: none;
  padding: 6px 12px;
  font-size: 12.5px;
  font-weight: 500;
  cursor: pointer;
  font-family: inherit;
  border-right: 1px solid var(--cet-line);
  transition: background 0.12s, color 0.12s;
}
.mode-btn:last-child { border-right: none; }
.mode-btn:hover:not(.active) {
  background: var(--cet-surface-2);
  color: var(--cet-text);
}
.mode-btn.active {
  background: var(--cet-brand);
  color: var(--cet-brand-fg);
}

.card {
  max-width: 640px;
  margin: 0 auto;
  background: var(--cet-card-bg);
  border: 1px solid var(--cet-card-border);
  border-radius: 12px;
  padding: 32px 28px;
  box-shadow: 0 4px 24px rgba(15, 23, 42, 0.06);
}
:root[data-theme="dark"] .card { box-shadow: 0 4px 24px rgba(0, 0, 0, 0.3); }

.loading { text-align: center; color: var(--cet-muted); padding: 40px 0; }

.error {
  background: var(--cet-verdict-bad-bg);
  border: 1px solid var(--cet-verdict-bad-border);
  color: var(--cet-verdict-bad-fg);
  padding: 8px 12px;
  border-radius: 6px;
  margin-bottom: 16px;
  font-size: 13px;
}

.direction {
  font-size: 12px;
  color: var(--cet-brand);
  letter-spacing: 0.1em;
  margin-bottom: 8px;
  text-transform: uppercase;
}

.hint-tag {
  margin-left: 8px;
  padding: 2px 8px;
  background: var(--cet-hint-bg);
  color: var(--cet-hint-fg);
  border-radius: 999px;
  font-size: 10px;
  letter-spacing: 0;
  text-transform: none;
  font-weight: 600;
}

.prompt {
  font-size: 32px;
  font-weight: 600;
  text-align: center;
  margin: 12px 0 28px;
  color: var(--cet-ink);
  word-break: break-word;
  line-height: 1.3;
}

.answer-row {
  display: flex;
  align-items: stretch;
  gap: 0;
  margin-bottom: 16px;
  background: var(--cet-input-bg);
  border: 1px solid var(--cet-input-border);
  border-radius: 8px;
  overflow: hidden;
}

.hint-prefix {
  display: inline-flex;
  align-items: center;
  padding: 0 12px;
  background: var(--cet-hint-bg);
  color: var(--cet-hint-fg);
  font-family: 'JetBrains Mono', 'Consolas', monospace;
  font-size: 18px;
  font-weight: 600;
  letter-spacing: 0.05em;
}

.answer-row input {
  flex: 1;
  background: transparent;
  border: none;
  outline: none;
  color: var(--cet-input-text);
  padding: 12px 14px;
  font-size: 18px;
  font-family: inherit;
}

.answer-row input:disabled { color: var(--cet-muted); }

.actions { display: flex; justify-content: center; }

.btn {
  padding: 10px 24px;
  border-radius: 8px;
  border: none;
  cursor: pointer;
  font-size: 14px;
  font-weight: 500;
  transition: transform 0.1s, background 0.15s;
  font-family: inherit;
}

.btn:disabled { opacity: 0.5; cursor: not-allowed; }

.btn.primary { background: var(--cet-brand); color: var(--cet-brand-fg); }
.btn.primary:hover:not(:disabled) { background: var(--cet-brand-2); }
.btn.primary:active:not(:disabled) { transform: translateY(1px); }

.btn.secondary {
  background: var(--cet-surface-2);
  color: var(--cet-text);
  border: 1px solid var(--cet-line);
  margin-top: 12px;
}
.btn.secondary:hover { background: var(--cet-line); }

.btn.ghost {
  background: transparent;
  color: var(--cet-muted);
  border: 1px solid var(--cet-line);
  padding: 8px 16px;
  font-size: 13px;
}
.btn.ghost:hover:not(:disabled) { border-color: var(--cet-brand); color: var(--cet-brand); }
.btn.ghost:disabled { opacity: 0.6; cursor: default; }

.verdict-actions { display: flex; gap: 10px; margin-top: 12px; align-items: center; }
.verdict-actions .btn { margin: 0; }

.verdict {
  margin-top: 24px;
  padding: 16px 20px;
  border-radius: 8px;
  text-align: center;
}

.verdict.ok {
  background: var(--cet-verdict-ok-bg);
  border: 1px solid var(--cet-verdict-ok-border);
}
.verdict.bad {
  background: var(--cet-verdict-bad-bg);
  border: 1px solid var(--cet-verdict-bad-border);
}

.verdict-icon { font-size: 20px; font-weight: 700; margin-bottom: 6px; }
.verdict.ok .verdict-icon { color: var(--cet-verdict-ok-fg); }
.verdict.bad .verdict-icon { color: var(--cet-verdict-bad-fg); }

.verdict-reason { font-size: 13px; color: var(--cet-text); margin-bottom: 10px; }

.verdict-answer { font-size: 14px; margin-bottom: 8px; }
.verdict-answer .label { color: var(--cet-muted); }
.verdict-answer .value { color: var(--cet-ink); font-weight: 600; margin-left: 4px; }

.done-title { text-align: center; margin-bottom: 12px; color: var(--cet-ink); }
.done-score { text-align: center; color: var(--cet-muted); margin-bottom: 24px; }
.card .done-title + .done-score + .btn { display: block; margin: 0 auto; }
</style>
