import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  {
    path: '/',
    component: () => import('@/layouts/MainLayout.vue'),
    children: [
      { path: '', redirect: '/clone' },
      { path: 'clone',     name: 'Clone',     component: () => import('@/views/SoundClone.vue') },
      { path: 'tts',       name: 'Tts',       component: () => import('@/views/TtsSynthesize.vue') },
      { path: 'tasks',     name: 'Tasks',     component: () => import('@/views/Tasks.vue') },
    ]
  },
  {
    path: '/:pathMatch(.*)*', redirect: '/clone'
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

export default router
