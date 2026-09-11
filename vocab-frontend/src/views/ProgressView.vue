<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import TopNav from '@/components/TopNav.vue'
import {
  fetchStats,
  fetchToday,
  fetchLists,
  type ListSummaryDto,
  type TodayResponse,
} from '@/api/vocab'

type Book = 'cet4' | 'cet6'

const levelToBook = (lv: string | null): Book =>
  lv === 'CET-6' ? 'cet6' : 'cet4'

const book = ref<Book>(levelToBook(localStorage.getItem('cet-agent-level')))
const loading = ref(false)
const stats = ref<{ total_words: number; reviewed: number; mastered: number; avg_forget_rate: number | null } | null>(null)
const today = ref<TodayResponse | null>(null)
const lists = ref<ListSummaryDto[]>([])

const STAGE_LABELS = ['未学', '1 天', '2 天', '4 天', '7 天', '15 天', '30 天']
const STAGE_COLORS = [
  'var(--cet-surface-2)',        // 0 never
  'var(--cet-hint-bg)',          // 1 warm yellow
  'var(--cet-brand-tint)',       // 2 pale green
  'var(--cet-brand-tint-2)',     // 3 light green
  'var(--cet-brand-2)',          // 4 green
  'var(--cet-brand)',            // 5 stronger green
  'var(--cet-brand-deep)',       // 6 mastered
]

async function refetchAll() {
  loading.value = true
  try {
    const [s, t, ls] = await Promise.all([
      fetchStats(book.value),
      fetchToday(book.value),
      fetchLists(book.value),
    ])
    stats.value = s
    today.value = t
    lists.value = ls
  } catch (e) {
    console.warn('[progress] fetch failed', e)
  } finally {
    loading.value = false
  }
}

onMounted(refetchAll)

function onLevelChange(lv: 'CET-4' | 'CET-6') {
  book.value = levelToBook(lv)
}

watch(book, refetchAll)

const kpiCards = computed(() => {
  const s = stats.value
  if (!s) return []
  const bookLabel = book.value === 'cet6' ? 'CET-6' : 'CET-4'
  const masteredPct = s.reviewed > 0 ? Math.round((s.mastered / s.reviewed) * 100) : 0
  const forgetPct = s.avg_forget_rate == null ? '—' : `${Math.round(s.avg_forget_rate * 100)}%`
  return [
    { label: '词量', value: s.total_words.toLocaleString(), hint: `${bookLabel} 全部词` },
    { label: '已复习', value: s.reviewed.toLocaleString(), hint: '不重复词数' },
    { label: '已掌握', value: `${s.mastered}`, hint: s.reviewed > 0 ? `${masteredPct}% 复习过词` : '≥2 次复习且遗忘率 ≤20%' },
    { label: '平均遗忘率', value: forgetPct, hint: '越低越好' },
  ]
})

const weakLists = computed(() => {
  return [...lists.value]
    .filter(l => l.recent_forget_rate !== null && l.reviewed > 0)
    .sort((a, b) => (b.recent_forget_rate ?? 0) - (a.recent_forget_rate ?? 0))
    .slice(0, 5)
})

const stageDistribution = computed(() => {
  const counts = new Array(STAGE_COLORS.length).fill(0)
  for (const l of lists.value) {
    const stage = l.last_review_date == null ? 0 : Math.max(1, l.ebbinghaus_stage ?? 0)
    counts[Math.min(stage, counts.length - 1)]++
  }
  return counts
})

function cellStyle(l: ListSummaryDto) {
  const stage = l.last_review_date == null ? 0 : Math.max(1, l.ebbinghaus_stage ?? 0)
  return {
    background: STAGE_COLORS[Math.min(stage, STAGE_COLORS.length - 1)],
    // brighter foreground on the darkest cells
    color: stage >= 5 ? 'var(--cet-brand-fg)' : 'var(--cet-text)',
  }
}

function cellTitle(l: ListSummaryDto) {
  const stage = l.last_review_date == null ? 0 : (l.ebbinghaus_stage ?? 0)
  const parts = [
    `List ${l.list_no}`,
    `阶段 ${STAGE_LABELS[Math.min(stage, STAGE_LABELS.length - 1)]}`,
    l.last_review_date ? `上次 ${l.last_review_date}` : '未复习',
    l.recent_forget_rate == null ? '' : `近期遗忘 ${Math.round(l.recent_forget_rate * 100)}%`,
    l.due ? '今日到期' : `${l.days_until_due}天后`,
  ]
  return parts.filter(Boolean).join(' · ')
}

function jumpToList(list_no: number) {
  // HomeView is now at /typing. Its own route.query watcher does a full
  // reload on change, so just changing the hash is enough.
  window.location.href = `/vocab/#/typing?list=${list_no}`
}

function askAgent(list_no: number) {
  const q = `讲讲 List ${list_no} 里我记不住的词`
  window.location.href = `/vocab/#/?ask=${encodeURIComponent(q)}`
}
</script>

<template>
  <TopNav active="progress" @level-change="onLevelChange" />
  <div class="progress-wrap">
    <main class="progress-page">
      <header class="page-head">
      <div>
        <h1>学习进度</h1>
        <p class="sub">
          {{ book === 'cet4' ? 'CET-4 高频词' : 'CET-6 高频词' }}
          <span v-if="today">· 今日 {{ today.date }}</span>
        </p>
      </div>
      <button class="refresh-btn" @click="refetchAll" :disabled="loading">
        {{ loading ? '刷新中…' : '刷新' }}
      </button>
    </header>

    <section class="kpi-row">
      <div class="kpi" v-for="k in kpiCards" :key="k.label">
        <div class="kpi-value">{{ k.value }}</div>
        <div class="kpi-label">{{ k.label }}</div>
        <div class="kpi-hint">{{ k.hint }}</div>
      </div>
      <div class="kpi" v-if="!kpiCards.length">
        <div class="kpi-value">—</div>
        <div class="kpi-label">加载中</div>
      </div>
    </section>

    <section class="card">
      <div class="card-head">
        <h2>今日队列</h2>
        <span class="card-sub" v-if="today">共 {{ today.lists.length }} 个 list</span>
      </div>
      <div v-if="today && today.lists.length" class="chip-row">
        <button
          v-for="l in today.lists"
          :key="l.list_no"
          class="chip"
          :class="{ 'chip-new': l.hit_reason === 'new' }"
          @click="jumpToList(l.list_no)"
          :title="`点击进入 List ${l.list_no}`"
        >
          <span class="chip-title">L{{ l.list_no }}</span>
          <span class="chip-reason">{{ l.hit_reason === 'new' ? '未学' : `阶段 ${l.ebbinghaus_stage}` }}</span>
        </button>
      </div>
      <div v-else-if="today" class="empty">今日无待复习内容 🎉</div>
      <div v-else class="empty">加载中…</div>
    </section>

    <section class="card">
      <div class="card-head">
        <h2>记忆热力图</h2>
        <span class="card-sub" v-if="lists.length">
          共 {{ lists.length }} 个 list · 悬停查看详情 · 点击进入
        </span>
      </div>
      <div class="legend">
        <span v-for="(c, i) in STAGE_COLORS" :key="i" class="legend-item">
          <span class="legend-swatch" :style="{ background: c }"></span>
          <span class="legend-label">{{ STAGE_LABELS[i] }}</span>
          <span class="legend-count">({{ stageDistribution[i] }})</span>
        </span>
      </div>
      <div class="heatmap">
        <button
          v-for="l in lists"
          :key="l.list_no"
          class="cell"
          :class="{ 'cell-due': l.due }"
          :style="cellStyle(l)"
          :title="cellTitle(l)"
          @click="jumpToList(l.list_no)"
        >{{ l.list_no }}</button>
      </div>
    </section>

    <section class="card">
      <div class="card-head">
        <h2>薄弱 list</h2>
        <span class="card-sub">按近期遗忘率排序 · 前 5</span>
      </div>
      <div v-if="weakLists.length" class="weak-table">
        <div class="weak-row weak-head">
          <span>List</span><span>近期遗忘</span><span>累计遗忘</span><span>阶段</span><span>上次</span><span></span>
        </div>
        <div class="weak-row" v-for="l in weakLists" :key="l.list_no">
          <span class="weak-cell weak-list">L{{ l.list_no }}</span>
          <span class="weak-cell weak-forget">{{ Math.round((l.recent_forget_rate ?? 0) * 100) }}%</span>
          <span class="weak-cell">{{ l.avg_forget_rate == null ? '—' : Math.round(l.avg_forget_rate * 100) + '%' }}</span>
          <span class="weak-cell">{{ STAGE_LABELS[Math.min(l.ebbinghaus_stage ?? 0, STAGE_LABELS.length - 1)] }}</span>
          <span class="weak-cell">{{ l.last_review_date ?? '—' }}</span>
          <div class="weak-actions">
            <button class="weak-cta" @click="jumpToList(l.list_no)">去复习</button>
            <button class="weak-cta weak-cta-ghost" @click="askAgent(l.list_no)" title="跳到对话页，让 agent 讲这个 list 里的错词">问 agent</button>
          </div>
        </div>
      </div>
      <div v-else class="empty">还没有薄弱数据，多背几个 list 就出来了。</div>
    </section>
    </main>
  </div>
</template>

<style scoped>
/* Wrap owns the full-viewport-width body-bg + its own scroll container.
   #app is height:100vh (main.css) so we can't rely on body scroll — the
   wrap gets an internal overflow instead. */
.progress-wrap {
  background: var(--cet-body-bg);
  height: calc(100vh - var(--cet-nav-h));
  overflow-y: auto;
  color: var(--cet-text);
  font-family: var(--cet-font);
}
.progress-page {
  max-width: 1000px;
  margin: 0 auto;
  padding: 24px 20px 60px;
}
.page-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  margin-bottom: 24px;
}
.page-head h1 {
  margin: 0;
  font-size: 26px;
  color: var(--cet-ink);
  font-weight: 700;
}
.page-head .sub {
  margin: 6px 0 0;
  color: var(--cet-muted);
  font-size: 13px;
}
.refresh-btn {
  padding: 6px 14px;
  border-radius: 6px;
  border: 1px solid var(--cet-line);
  background: var(--cet-surface);
  color: var(--cet-text);
  font-size: 13px;
  cursor: pointer;
}
.refresh-btn:hover { border-color: var(--cet-brand); color: var(--cet-brand); }
.refresh-btn:disabled { opacity: 0.5; cursor: default; }

.kpi-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-bottom: 20px;
}
.kpi {
  background: var(--cet-card-bg);
  border: 1px solid var(--cet-card-border);
  border-radius: 10px;
  padding: 16px 18px;
}
.kpi-value {
  font-size: 26px;
  font-weight: 700;
  color: var(--cet-ink);
  line-height: 1.1;
}
.kpi-label {
  margin-top: 6px;
  font-size: 13px;
  color: var(--cet-text);
}
.kpi-hint {
  margin-top: 2px;
  font-size: 11px;
  color: var(--cet-muted);
}

.card {
  background: var(--cet-card-bg);
  border: 1px solid var(--cet-card-border);
  border-radius: 10px;
  padding: 16px 18px;
  margin-bottom: 16px;
}
.card-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin-bottom: 12px;
}
.card-head h2 {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  color: var(--cet-ink);
}
.card-sub { font-size: 12px; color: var(--cet-muted); }
.empty { color: var(--cet-muted); font-size: 13px; padding: 8px 0; }

.chip-row { display: flex; flex-wrap: wrap; gap: 8px; }
.chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border-radius: 20px;
  border: 1px solid var(--cet-line);
  background: var(--cet-surface);
  color: var(--cet-text);
  font-size: 12px;
  cursor: pointer;
}
.chip:hover { border-color: var(--cet-brand); color: var(--cet-brand); }
.chip-new {
  background: var(--cet-brand-tint);
  border-color: var(--cet-brand-tint-2);
  color: var(--cet-brand-deep);
}
.chip-title { font-weight: 600; }
.chip-reason { opacity: 0.8; }

.legend {
  display: flex;
  flex-wrap: wrap;
  gap: 10px 16px;
  font-size: 11px;
  color: var(--cet-muted);
  margin-bottom: 12px;
}
.legend-item { display: inline-flex; align-items: center; gap: 4px; }
.legend-swatch {
  display: inline-block;
  width: 12px;
  height: 12px;
  border-radius: 3px;
  border: 1px solid var(--cet-line);
}
.legend-count { opacity: 0.7; }

.heatmap {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(38px, 1fr));
  gap: 4px;
}
.cell {
  aspect-ratio: 1 / 1;
  border-radius: 4px;
  border: 1px solid transparent;
  font-size: 11px;
  cursor: pointer;
  color: inherit;
  padding: 0;
  transition: transform 0.05s, box-shadow 0.05s;
}
.cell:hover {
  transform: scale(1.15);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
  z-index: 1;
  position: relative;
}
.cell-due {
  outline: 2px solid var(--cet-brand);
  outline-offset: -1px;
}

.weak-table { display: flex; flex-direction: column; gap: 6px; }
.weak-row {
  display: grid;
  grid-template-columns: 60px 100px 100px 80px 1fr 160px;
  align-items: center;
  padding: 8px 10px;
  border-radius: 6px;
  background: var(--cet-surface-2);
  font-size: 13px;
}
.weak-actions {
  display: flex;
  gap: 6px;
  justify-self: end;
}
.weak-head {
  background: transparent;
  color: var(--cet-muted);
  font-size: 11px;
  padding: 0 10px;
}
.weak-list { font-weight: 600; color: var(--cet-ink); }
.weak-forget { color: var(--cet-verdict-bad-fg); font-weight: 600; }
.weak-cell { color: var(--cet-text); }
.weak-cta {
  padding: 4px 10px;
  font-size: 12px;
  border-radius: 4px;
  border: 1px solid var(--cet-brand);
  background: transparent;
  color: var(--cet-brand);
  cursor: pointer;
  justify-self: end;
}
.weak-cta:hover { background: var(--cet-brand-tint); }
.weak-cta-ghost {
  border-color: var(--cet-line);
  color: var(--cet-muted);
}
.weak-cta-ghost:hover {
  border-color: var(--cet-brand);
  color: var(--cet-brand);
  background: transparent;
}

@media (max-width: 700px) {
  .kpi-row { grid-template-columns: repeat(2, 1fr); }
  .weak-row { grid-template-columns: 44px 60px 60px 50px 1fr 130px; font-size: 12px; }
  .cell { font-size: 10px; }
}
</style>
