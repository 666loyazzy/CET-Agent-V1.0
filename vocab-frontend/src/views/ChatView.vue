<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { marked } from 'marked'
import { useRoute, useRouter } from 'vue-router'
import TopNav from '@/components/TopNav.vue'
import { useClickEffect } from '@/composables/useClickEffect'

type Role = 'user' | 'assistant'
interface Message {
  role: Role
  content: string
}

const messages = ref<Message[]>([])
const input = ref('')
const pending = ref('')
const streaming = ref(false)
const currentMode = ref<string | null>(null)
const clickEffectEnabled = ref(true)
const level = ref<'CET-4' | 'CET-6'>('CET-4')
const scrollEl = ref<HTMLElement | null>(null)

const route = useRoute()
const router = useRouter()

onMounted(() => {
  const savedLv = localStorage.getItem('cet-agent-level')
  if (savedLv === 'CET-4' || savedLv === 'CET-6') level.value = savedLv
  const savedFx = localStorage.getItem('cet-agent-click-effect')
  if (savedFx !== null) clickEffectEnabled.value = savedFx === '1'

  // Auto-submit if the user landed here via a "问 agent" link from another
  // view (e.g. ProgressView weak list). Clear the query afterwards so a
  // page refresh doesn't re-fire the same question.
  const ask = route.query.ask
  if (typeof ask === 'string' && ask.trim()) {
    input.value = ask
    nextTick(() => {
      send()
      router.replace({ query: {} })
    })
  }
})

watch(clickEffectEnabled, (v) => {
  localStorage.setItem('cet-agent-click-effect', v ? '1' : '0')
})

useClickEffect(
  () => clickEffectEnabled.value,
  () => level.value,
)

function onLevelChange(lv: 'CET-4' | 'CET-6') {
  level.value = lv
}

const MODE_LABELS: Record<string, string> = {
  writing: '写作',
  translation: '翻译',
  reading: '阅读',
  listening: '听力',
  study_plan: '学习规划',
  intro: '首次交互',
}
const modeLabel = computed(() =>
  currentMode.value ? MODE_LABELS[currentMode.value] || currentMode.value : ''
)
function render(md: string): string {
  if (!md) return ''
  try {
    return marked.parse(md) as string
  } catch {
    return md
  }
}

function reset() {
  messages.value = []
  pending.value = ''
  currentMode.value = null
}

async function scrollToBottom() {
  await nextTick()
  const el = scrollEl.value
  if (el) el.scrollTop = el.scrollHeight
}

function onEnter(event: KeyboardEvent) {
  if (event.shiftKey) return
  event.preventDefault()
  send()
}

async function send() {
  const text = input.value.trim()
  if (!text || streaming.value) return
  messages.value.push({ role: 'user', content: text })
  input.value = ''
  pending.value = ''
  streaming.value = true
  scrollToBottom()
  try {
    await streamResponse()
  } catch (err: any) {
    messages.value.push({
      role: 'assistant',
      content: `**请求失败**：${err?.message || err}`,
    })
  } finally {
    streaming.value = false
    scrollToBottom()
  }
}
async function streamResponse() {
  const body = {
    messages: messages.value.map((m) => ({ role: m.role, content: m.content })),
    mode: currentMode.value || null,
    level: level.value || null,
  }
  const res = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`)

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let idx: number
    while ((idx = buffer.indexOf('\n\n')) !== -1) {
      const raw = buffer.slice(0, idx)
      buffer = buffer.slice(idx + 2)
      handleSseFrame(raw)
    }
  }
  if (pending.value) {
    messages.value.push({ role: 'assistant', content: pending.value })
    pending.value = ''
  }
}

function handleSseFrame(raw: string) {
  const lines = raw.split('\n')
  let event = 'message'
  let data = ''
  for (const line of lines) {
    if (line.startsWith('event:')) event = line.slice(6).trim()
    else if (line.startsWith('data:')) data += line.slice(5).trim()
  }
  if (!data) return
  if (event === 'meta') {
    try {
      const parsed = JSON.parse(data)
      if (parsed.mode) currentMode.value = parsed.mode
    } catch {}
  } else if (event === 'delta') {
    try {
      const parsed = JSON.parse(data)
      pending.value += parsed.text || ''
      scrollToBottom()
    } catch {}
  } else if (event === 'error') {
    try {
      const parsed = JSON.parse(data)
      pending.value += `\n\n**错误**：${parsed.message}`
    } catch {}
  }
}
</script>
<template>
  <TopNav active="chat" @level-change="onLevelChange" />
  <div class="chat-wrap">
    <div class="sub-header">
      <p class="tag-line">四六级 AI 备考助手 · Phase 1 MVP</p>
      <div class="controls">
        <span v-if="currentMode" class="mode-chip">{{ modeLabel }}</span>
        <label class="fx-toggle" title="点击页面时飘出四六级单词">
          <input type="checkbox" v-model="clickEffectEnabled" />
          <span>点击特效</span>
        </label>
        <button class="reset-btn" @click="reset">清空</button>
      </div>
    </div>

    <main ref="scrollEl" class="messages">
      <div v-if="!messages.length && !streaming" class="empty">
        <p>你准备考四级还是六级？</p>
        <p class="empty-sub">目前最想提升哪一项：写作、翻译、阅读、听力，还是整体规划？</p>
      </div>

      <div v-for="(m, i) in messages" :key="i" class="row" :class="m.role">
        <div class="bubble prose" v-html="render(m.content)"></div>
      </div>

      <div v-if="streaming" class="row assistant">
        <div class="bubble prose" v-html="render(pending)"></div>
      </div>
    </main>

    <footer class="composer">
      <form @submit.prevent="send" class="composer-form">
        <textarea
          v-model="input"
          @keydown.enter="onEnter"
          rows="2"
          :disabled="streaming"
          placeholder="输入你的问题、作文、译文，或答题串（如 26A 27F ...）。Shift+Enter 换行。"
        ></textarea>
        <button type="submit" :disabled="streaming || !input.trim()">发送</button>
      </form>
      <p class="hint">默认延迟揭示答案：先写出你的答案，我再给解析。</p>
    </footer>
  </div>
</template>
<style scoped>
.chat-wrap {
  display: flex;
  flex-direction: column;
  height: calc(100vh - var(--cet-nav-h));
  background: var(--cet-body-bg);
  color: var(--cet-text);
  font-family: var(--cet-font);
}

.sub-header {
  width: 100%;
  max-width: 780px;
  margin: 0 auto;
  padding: 10px 24px 6px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12px;
}
.tag-line { color: var(--cet-muted); margin: 0; }
.controls { display: flex; align-items: center; gap: 12px; }
.mode-chip {
  padding: 2px 8px;
  border-radius: 4px;
  background: var(--cet-brand-tint);
  color: var(--cet-brand-deep);
  font-size: 11px;
  font-weight: 500;
}
.fx-toggle {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--cet-muted);
  cursor: pointer;
  user-select: none;
}
.fx-toggle input { accent-color: var(--cet-brand); cursor: pointer; }
.reset-btn {
  background: transparent;
  border: none;
  color: var(--cet-muted);
  cursor: pointer;
  font-size: 12px;
  padding: 0;
}
.reset-btn:hover { color: var(--cet-text); }

.messages {
  flex: 1;
  overflow-y: auto;
  padding: 8px 24px 16px;
  width: 100%;
  max-width: 780px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.empty {
  text-align: center;
  color: var(--cet-muted);
  padding-top: 64px;
}
.empty p { margin: 4px 0; }
.empty-sub { font-size: 13px; }

.row { display: flex; }
.row.user { justify-content: flex-end; }
.row.assistant { justify-content: flex-start; }

.bubble {
  max-width: 85%;
  padding: 10px 14px;
  border-radius: 10px;
  line-height: 1.55;
  font-size: 14px;
  word-wrap: break-word;
  white-space: normal;
}
.row.user .bubble {
  background: var(--cet-brand);
  color: var(--cet-brand-fg);
}
.row.assistant .bubble {
  background: var(--cet-surface);
  border: 1px solid var(--cet-line);
  color: var(--cet-text);
}
:root[data-theme="dark"] .row.user .bubble {
  color: var(--cet-brand-fg);
}

.composer {
  border-top: 1px solid var(--cet-line);
  background: var(--cet-surface);
  padding: 12px 24px 14px;
  width: 100%;
}
.composer-form {
  max-width: 780px;
  margin: 0 auto;
  display: flex;
  gap: 8px;
  align-items: flex-end;
}
.composer textarea {
  flex: 1;
  padding: 8px 12px;
  border-radius: 6px;
  border: 1px solid var(--cet-input-border);
  background: var(--cet-input-bg);
  color: var(--cet-input-text);
  font-size: 14px;
  font-family: inherit;
  resize: none;
  outline: none;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.composer textarea:focus {
  border-color: var(--cet-brand);
  box-shadow: 0 0 0 2px var(--cet-brand-tint);
}
.composer textarea:disabled { opacity: 0.6; }

.composer button {
  padding: 8px 18px;
  background: var(--cet-brand);
  color: var(--cet-brand-fg);
  border: none;
  border-radius: 6px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
}
.composer button:hover:not(:disabled) { background: var(--cet-brand-deep); }
.composer button:disabled { opacity: 0.5; cursor: not-allowed; }

.hint {
  max-width: 780px;
  margin: 6px auto 0;
  color: var(--cet-muted);
  font-size: 11px;
}
</style>






