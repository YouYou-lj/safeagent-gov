import { configureApiBaseUrl } from '@/utils/request'

interface DesktopBootstrap {
  apiBaseUrl: string
  token: string
  dataDir: string
  pid: number
}

export function isTauriDesktop(): boolean {
  return '__TAURI_INTERNALS__' in globalThis
}

function delay(milliseconds: number): Promise<void> {
  return new Promise((resolve) => globalThis.setTimeout(resolve, milliseconds))
}

export async function bootstrapDesktop(): Promise<DesktopBootstrap | null> {
  if (!isTauriDesktop()) return null
  const { invoke } = await import('@tauri-apps/api/core')
  let lastError: unknown
  for (let attempt = 0; attempt < 100; attempt += 1) {
    try {
      const value = await invoke<DesktopBootstrap>('desktop_bootstrap')
      if (!value.token || !value.apiBaseUrl) throw new Error('桌面启动信息不完整')
      configureApiBaseUrl(value.apiBaseUrl)
      return value
    } catch (error) {
      lastError = error
      await delay(150)
    }
  }
  throw new Error(`本地安全服务未能启动：${String(lastError ?? 'unknown error')}`)
}
