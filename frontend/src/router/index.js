import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  {
    path: '/',
    component: () => import('@/layouts/MainLayout.vue'),
    children: [
      { path: '', redirect: '/dashboard' },
      { path: 'dashboard',  name: 'Dashboard',  component: () => import('@/views/Dashboard.vue') },
      { path: 'clone',     name: 'Clone',     component: () => import('@/views/VoiceClone.vue') },
      { path: 'tasks',     name: 'Tasks',     component: () => import('@/views/Tasks.vue') },
    ]
  },
  {
    path: '/:pathMatch(.*)*', redirect: '/dashboard'
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

export default router
