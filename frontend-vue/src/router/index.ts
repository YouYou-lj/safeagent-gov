import { createRouter, createWebHistory } from 'vue-router'

import { commonRoutes } from '@/router/routes/common'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: commonRoutes,
  scrollBehavior: () => ({ top: 0 }),
})

router.afterEach((route) => {
  document.title = `${route.meta.title} · GovSafeAgent`
})

export default router
