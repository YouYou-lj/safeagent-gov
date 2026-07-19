import axios, { AxiosError } from 'axios'
import { ElMessage } from 'element-plus'

import { pinia } from '@/stores'
import { useAuthStore } from '@/stores/auth'

interface ErrorPayload {
  detail?: string | Record<string, unknown>[]
}

export const request = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? '',
  timeout: 30_000,
  headers: { 'Content-Type': 'application/json' },
})

export function configureApiBaseUrl(baseUrl: string): void {
  const normalized = baseUrl.trim().replace(/\/$/, '')
  if (!/^http:\/\/127\.0\.0\.1:\d{4,5}$/.test(normalized)) {
    throw new Error('桌面 API 地址必须是 127.0.0.1 回环端口')
  }
  request.defaults.baseURL = normalized
}

request.interceptors.request.use((config) => {
  const auth = useAuthStore(pinia)
  if (auth.token) config.headers.Authorization = `Bearer ${auth.token}`
  return config
})

request.interceptors.response.use(
  (response) => response,
  (rawError: unknown) => {
    const error = rawError as AxiosError<ErrorPayload>
    const detail = error.response?.data?.detail
    const message =
      typeof detail === 'string'
        ? detail
        : error.code === 'ECONNABORTED'
          ? '请求超时，请检查服务状态'
          : `接口请求失败（${error.response?.status ?? '网络异常'}）`
    ElMessage.error(message)
    return Promise.reject(error)
  },
)
