// Wraps the global window.CET4Effect IIFE (loaded via <script> in
// index.html) as a Vue composable. Re-inits on level change and when
// re-enabled; auto-destroys on unmount.

import { onUnmounted, watchEffect } from 'vue'
import { loadClickWords } from '@/utils/wordlist'

interface CET4Effect {
  init(opts: { words: [string, string][] }): () => void
}

declare global {
  interface Window {
    CET4Effect?: CET4Effect
  }
}

export function useClickEffect(
  enabled: () => boolean,
  level: () => 'CET-4' | 'CET-6',
): void {
  let destroy: (() => void) | null = null
  let version = 0

  async function apply() {
    const localVersion = ++version
    if (destroy) {
      destroy()
      destroy = null
    }
    if (!enabled()) return
    if (!window.CET4Effect) return
    try {
      const words = await loadClickWords(level())
      if (localVersion !== version) return
      destroy = window.CET4Effect.init({ words })
    } catch (e) {
      console.warn('[click-effect]', e)
    }
  }

  watchEffect(apply)

  onUnmounted(() => {
    version++
    if (destroy) {
      destroy()
      destroy = null
    }
  })
}
