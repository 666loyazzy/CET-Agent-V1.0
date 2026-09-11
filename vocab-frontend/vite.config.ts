import { fileURLToPath, URL } from 'node:url'

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import vueJsx from '@vitejs/plugin-vue-jsx'

// https://vitejs.dev/config/
// Deployed under /vocab/ inside cet-agent. Build output goes to ../frontend/vocab
// so FastAPI can serve it as static files. Hash router keeps SPA routing
// client-side (no server fallback needed).
export default defineConfig({
  base: '/vocab/',
  plugins: [vue(), vueJsx()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  },
  build: {
    outDir: '../frontend/vocab',
    emptyOutDir: true
  },
  server: {
    port: 9000,
    host: '0.0.0.0',
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true
      },
      '/lyc8503': {
        target: 'https://cdn.jsdelivr.net/gh/lyc8503',
        secure: false,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/lyc8503/, '')
      }
    }
  }
})
