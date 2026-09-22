<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'

const props = defineProps<{
  active: 'chat' | 'writing' | 'typing' | 'dictation' | 'progress'
}>()

const emit = defineEmits<{
  (e: 'level-change', level: 'CET-4' | 'CET-6'): void
  (e: 'theme-change', theme: 'light' | 'dark'): void
}>()

const level = ref<'CET-4' | 'CET-6'>('CET-4')
const theme = ref<'light' | 'dark'>('light')

function applyTheme(t: 'light' | 'dark') {
  document.documentElement.setAttribute('data-theme', t)
}

onMounted(() => {
  const savedLevel = localStorage.getItem('cet-agent-level')
  if (savedLevel === 'CET-4' || savedLevel === 'CET-6') level.value = savedLevel
  const savedTheme = localStorage.getItem('cet-agent-theme')
  if (savedTheme === 'dark' || savedTheme === 'light') theme.value = savedTheme
  applyTheme(theme.value)
})

watch(level, (v) => {
  localStorage.setItem('cet-agent-level', v)
  emit('level-change', v)
})

watch(theme, (v) => {
  localStorage.setItem('cet-agent-theme', v)
  applyTheme(v)
  emit('theme-change', v)
})

function pick(lv: 'CET-4' | 'CET-6') {
  level.value = lv
}

function toggleTheme() {
  theme.value = theme.value === 'dark' ? 'light' : 'dark'
}
</script>

<template>
  <nav class="cet-topnav">
    <div class="cet-topnav-inner">
      <a href="/vocab/#/" class="cet-brand">
        <span class="cet-brand-icon">C</span>
        <span>CET Agent</span>
      </a>
      <div class="cet-nav-links">
        <a href="/vocab/#/" class="cet-nav-link" :class="{ active: props.active === 'chat' }">对话</a>
        <a href="/vocab/#/writing" class="cet-nav-link" :class="{ active: props.active === 'writing' }">作文</a>
        <a href="/vocab/#/typing" class="cet-nav-link" :class="{ active: props.active === 'typing' }">打字</a>
        <a href="/vocab/#/dictation" class="cet-nav-link" :class="{ active: props.active === 'dictation' }">默写</a>
        <a href="/vocab/#/progress" class="cet-nav-link" :class="{ active: props.active === 'progress' }">进度</a>
      </div>
      <div class="cet-nav-spacer"></div>
      <div class="cet-nav-right">
        <div class="cet-level">
          <button type="button" class="cet-level-btn" :class="{ active: level === 'CET-4' }" @click="pick('CET-4')">CET-4</button>
          <button type="button" class="cet-level-btn" :class="{ active: level === 'CET-6' }" @click="pick('CET-6')">CET-6</button>
        </div>
        <button type="button" class="cet-theme-toggle" :title="theme === 'dark' ? '切换浅色' : '切换深色'" @click="toggleTheme">
          <span v-if="theme === 'dark'">☀</span><span v-else>◐</span>
        </button>
      </div>
    </div>
  </nav>
</template>
