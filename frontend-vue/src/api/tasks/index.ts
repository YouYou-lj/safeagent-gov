import { request } from '@/utils/request'
import type { JsonObject, TaskRecord, TaskRuntimeMetrics } from '@/types/api'

export interface CreateTaskPayload {
  kind: 'security_check' | 'agent' | 'skill_scan' | 'evaluation'
  priority: 'critical' | 'high' | 'medium' | 'low'
  payload: JsonObject
  idempotency_key?: string
}

export async function getTaskMetrics(): Promise<TaskRuntimeMetrics> {
  return (await request.get<TaskRuntimeMetrics>('/api/tasks/metrics')).data
}

export async function getTasks(limit = 100): Promise<TaskRecord[]> {
  return (await request.get<TaskRecord[]>('/api/tasks', { params: { limit } })).data
}

export async function getDeadLetters(limit = 100): Promise<TaskRecord[]> {
  return (await request.get<TaskRecord[]>('/api/tasks/dead-letter', { params: { limit } })).data
}

export async function createTask(payload: CreateTaskPayload): Promise<TaskRecord> {
  return (await request.post<TaskRecord>('/api/tasks/submit', payload)).data
}
