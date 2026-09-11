import { createRouter, createWebHashHistory } from 'vue-router'
import HomeView from '../views/HomeView.vue'

const router = createRouter({
  history: createWebHashHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      name: '对话',
      component: () => import('../views/ChatView.vue'),
      alias: '/chat',
    },
    {
      path: '/typing',
      name: '打字',
      component: HomeView,
    },
    {
      path: '/search',
      name: '搜索',
      component: () => import('../views/SearchView.vue')
    },
    {
      path: '/dictation',
      name: '默写',
      component: () => import('../views/DictationView.vue')
    },
    {
      path: '/progress',
      name: '进度',
      component: () => import('../views/ProgressView.vue')
    },
  ]
})

export default router
