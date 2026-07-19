import { request } from '@/utils/request'
import type { JsonObject } from '@/types/api'

export type ManifestFormat = 'auto' | 'json' | 'yaml'
export type DataClassification = 'public' | 'internal' | 'confidential' | 'restricted'
export type ModelMessageRole = 'system' | 'user' | 'assistant'
export type EphemeralProvider =
  | 'openai'
  | 'openai-responses'
  | 'anthropic'
  | 'gemini'
  | 'azure-openai'
  | 'aws-bedrock'
  | 'vertex-ai'
  | 'deepseek'
  | 'qwen'
  | 'kimi'
  | 'ollama'
  | 'vllm'

export interface ModelMessage {
  role: ModelMessageRole
  content: string
}

export interface McpManifestScanPayload {
  content: string
  format: ManifestFormat
  source_name: string
}

export interface EphemeralProviderPayload {
  provider: EphemeralProvider
  model: string
  endpoint?: string
  api_key?: string
  timeout_seconds: number
}

export interface EphemeralChatPayload extends EphemeralProviderPayload {
  messages: ModelMessage[]
  max_output_tokens: number
  temperature: number
  data_classification: DataClassification
}

export interface AgentInspectionPayload {
  task: string
  scenario: string
  document_text?: string
  document_source?: string
}

export interface WorkbenchResult extends JsonObject {
  trace_id?: string
  risk_level?: string
  risk_score?: number
  recommendation?: string
}

export async function createSkillScan(file: File): Promise<WorkbenchResult> {
  const payload = new FormData()
  payload.append('file', file)
  return (
    await request.post<WorkbenchResult>('/api/skill/scan', payload, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  ).data
}

export async function createMcpManifestScan(payload: McpManifestScanPayload): Promise<WorkbenchResult> {
  return (await request.post<WorkbenchResult>('/api/mcp/scan', payload)).data
}

export async function createAgentInspection(payload: AgentInspectionPayload): Promise<WorkbenchResult> {
  return (await request.post<WorkbenchResult>('/api/agent/run', payload)).data
}

export async function createEphemeralConnectionTest(
  payload: EphemeralProviderPayload,
): Promise<WorkbenchResult> {
  return (await request.post<WorkbenchResult>('/api/model/test-connection', payload)).data
}

export async function createEphemeralModelChat(payload: EphemeralChatPayload): Promise<WorkbenchResult> {
  return (await request.post<WorkbenchResult>('/api/model/session/chat', payload)).data
}
