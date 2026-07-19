import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import { commonRoutes } from '@/router/routes/common'
import { useAuthStore } from '@/stores/auth'

describe('控制台路由契约', () => {
  it('注册完整的十二项安全治理页面', () => {
    const pages = commonRoutes[0]?.children ?? []
    expect(pages).toHaveLength(12)
    expect(pages.every((page) => page.meta?.title && page.meta?.description && page.meta?.icon)).toBe(true)
    expect(new Set(pages.map((page) => page.name)).size).toBe(12)
    expect(pages.some((page) => page.name === 'SecurityWorkbench' && page.path === 'workbench')).toBe(true)
  })
})

describe('访问身份状态', () => {
  beforeEach(() => {
    globalThis.localStorage.clear()
    setActivePinia(createPinia())
  })

  it('仅持久化 Token，并可读取展示性 Claims', () => {
    const auth = useAuthStore()
    const payload = globalThis.btoa(JSON.stringify({ sub: 'reviewer-1', role: 'reviewer', tenant_id: 'tenant-a' }))
    auth.setToken(`header.${payload}.signature`)

    expect(auth.isConfigured).toBe(true)
    expect(auth.role).toBe('reviewer')
    expect(auth.subject).toBe('reviewer-1')
    expect(auth.tenantId).toBe('tenant-a')
    expect(globalThis.localStorage.getItem('safeagent-gov-access-token')).toBe(auth.token)

    auth.clearToken()
    expect(auth.isConfigured).toBe(false)
    expect(globalThis.localStorage.getItem('safeagent-gov-access-token')).toBeNull()
  })
})
