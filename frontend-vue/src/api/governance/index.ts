import { request } from '@/utils/request'
import type {
  ApprovalItem,
  GraphHealth,
  GraphStats,
  JsonObject,
  ModelRegistrySnapshot,
  SkillRegistrySnapshot,
} from '@/types/api'

export async function getGraphStats(): Promise<GraphStats> {
  return (await request.get<GraphStats>('/api/graphify/stats')).data
}

export async function getGraphHealth(): Promise<GraphHealth> {
  return (await request.get<GraphHealth>('/api/graphify/health')).data
}

export async function createGraphSearch(payload: JsonObject): Promise<JsonObject> {
  return (await request.post<JsonObject>('/api/graphify/search', payload)).data
}

export async function createGraphBuild(): Promise<JsonObject> {
  return (await request.post<JsonObject>('/api/graphify/build')).data
}

export async function createRouterPlan(payload: JsonObject): Promise<JsonObject> {
  return (await request.post<JsonObject>('/api/router/plan', payload)).data
}

export async function getSkillRegistry(): Promise<SkillRegistrySnapshot> {
  return (await request.get<SkillRegistrySnapshot>('/api/skills/registry')).data
}

export async function getSkillMetrics(): Promise<JsonObject> {
  return (await request.get<JsonObject>('/api/skills/metrics')).data
}

export async function getModelProviders(): Promise<ModelRegistrySnapshot> {
  return (await request.get<ModelRegistrySnapshot>('/api/model/providers')).data
}

export async function getModelMetrics(): Promise<JsonObject> {
  return (await request.get<JsonObject>('/api/model/metrics')).data
}

export async function createModelChat(payload: JsonObject): Promise<JsonObject> {
  return (await request.post<JsonObject>('/api/model/chat', payload)).data
}

export async function createToolCheck(payload: JsonObject): Promise<JsonObject> {
  return (await request.post<JsonObject>('/api/tool/check', payload)).data
}

export async function getPendingApprovals(): Promise<{ items: ApprovalItem[] }> {
  return (await request.get<{ items: ApprovalItem[] }>('/api/tool/pending')).data
}

export async function createApproval(payload: JsonObject): Promise<JsonObject> {
  return (await request.post<JsonObject>('/api/tool/approve', payload)).data
}

export async function getAuditTrace(traceId: string): Promise<JsonObject> {
  return (await request.get<JsonObject>(`/api/audit/${encodeURIComponent(traceId)}`)).data
}

export async function getAuditVerification(traceId: string): Promise<JsonObject> {
  return (await request.get<JsonObject>(`/api/audit/${encodeURIComponent(traceId)}/verify`)).data
}

export async function createEvaluation(evalType: string): Promise<JsonObject> {
  return (await request.post<JsonObject>('/api/eval/run', { eval_type: evalType })).data
}

export async function getEvaluationResults(): Promise<JsonObject> {
  return (await request.get<JsonObject>('/api/eval/results')).data
}

export async function createPolicyCanary(version: string, rolloutPercent: number): Promise<JsonObject> {
  return (
    await request.post<JsonObject>('/api/policy/tool/canary', {
      version,
      rollout_percent: rolloutPercent,
    })
  ).data
}

export async function createPolicyPromotion(): Promise<JsonObject> {
  return (await request.post<JsonObject>('/api/policy/tool/promote')).data
}

export async function createPolicyRollback(): Promise<JsonObject> {
  return (await request.post<JsonObject>('/api/policy/tool/rollback')).data
}
