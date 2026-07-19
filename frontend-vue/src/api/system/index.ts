import { request } from '@/utils/request'
import type { HealthResponse, JsonObject } from '@/types/api'

export async function getHealth(): Promise<HealthResponse> {
  return (await request.get<HealthResponse>('/health')).data
}

export async function getPolicyStatus(): Promise<JsonObject> {
  return (await request.get<JsonObject>('/api/policy/tool/status')).data
}

export async function getAuthIdentity(): Promise<JsonObject> {
  return (await request.get<JsonObject>('/api/auth/me')).data
}
