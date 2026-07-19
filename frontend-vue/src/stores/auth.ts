import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

const TOKEN_STORAGE_KEY = 'safeagent-gov-access-token'

interface TokenClaims {
  role?: string
  sub?: string
  tenant_id?: string
}

function readStoredToken(): string {
  return globalThis.localStorage?.getItem(TOKEN_STORAGE_KEY) ?? ''
}

function decodeClaims(token: string): TokenClaims {
  const payload = token.split('.')[1]
  if (!payload) return {}
  try {
    const normalized = payload.replaceAll('-', '+').replaceAll('_', '/')
    const decoded: unknown = JSON.parse(globalThis.atob(normalized))
    if (typeof decoded !== 'object' || decoded === null) return {}
    const record = decoded as Record<string, unknown>
    return {
      role: typeof record.role === 'string' ? record.role : undefined,
      sub: typeof record.sub === 'string' ? record.sub : undefined,
      tenant_id: typeof record.tenant_id === 'string' ? record.tenant_id : undefined,
    }
  } catch {
    return {}
  }
}

export const useAuthStore = defineStore('auth', () => {
  const token = ref(readStoredToken())
  const claims = computed(() => decodeClaims(token.value))
  const isConfigured = computed(() => token.value.length > 0)
  const role = computed(() => claims.value.role ?? '未识别')
  const subject = computed(() => claims.value.sub ?? '未识别')
  const tenantId = computed(() => claims.value.tenant_id ?? '未识别')

  function setToken(value: string): void {
    token.value = value.trim()
    if (token.value) globalThis.localStorage?.setItem(TOKEN_STORAGE_KEY, token.value)
    else globalThis.localStorage?.removeItem(TOKEN_STORAGE_KEY)
  }

  function clearToken(): void {
    setToken('')
  }

  function setEphemeralToken(value: string): void {
    token.value = value.trim()
    globalThis.localStorage?.removeItem(TOKEN_STORAGE_KEY)
  }

  return { token, claims, isConfigured, role, subject, tenantId, setToken, setEphemeralToken, clearToken }
})
