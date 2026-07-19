import { request } from '@/utils/request'
import type { JsonObject } from '@/types/api'

export interface AgentRunPayload {
  task: string
  scenario: string
  document_text?: string
  document_source?: string
  skill_package_path?: string
}

export async function createAgentRun(payload: AgentRunPayload): Promise<JsonObject> {
  return (await request.post<JsonObject>('/api/agent/run', payload)).data
}
