export type JsonObject = Record<string, unknown>

export interface HealthResponse {
  status: string
  service?: string
  version?: string
}

export interface MetricItem {
  label: string
  value: string | number
  detail?: string
  tone?: 'default' | 'success' | 'warning' | 'danger'
}

export interface TaskPoolMetrics {
  workers: number
  queue_capacity: number
  pool: string
  queue_depth: number
  active_tasks: number
  max_queue_depth: number
  max_active_tasks: number
  leased_tasks: number
  dead_letters: number
}

export interface TaskRuntimeMetrics {
  running: boolean
  accepted: number
  succeeded: number
  failed: number
  rejected: number
  mode: 'in_memory' | 'redis_dramatiq'
  recovered: number
  dead_lettered: number
  pools: TaskPoolMetrics[]
  [key: string]: unknown
}

export interface TaskRecord {
  task_id: string
  trace_id: string
  kind: string
  priority: string
  status: string
  created_at: string
  updated_at: string
  delivery_count: number
  recovered_count: number
  last_worker_id?: string | null
  lease_expires_at?: string | null
  result?: JsonObject | null
  error_code?: string | null
  error_message?: string | null
  [key: string]: unknown
}

export interface GraphStats {
  node_count: number
  edge_count: number
  node_types: Record<string, number>
  [key: string]: unknown
}

export interface GraphHealth {
  healthy: boolean
  status?: string
  [key: string]: unknown
}

export interface ModelProvider {
  provider_id: string
  display_name: string
  protocol: string
  enabled: boolean
  model: string
  private_deployment: boolean
  capabilities: string[]
  [key: string]: unknown
}

export interface ModelRegistrySnapshot {
  provider_count: number
  enabled_count: number
  source_digest: string
  providers: ModelProvider[]
}

export interface SkillDefinition {
  name: string
  version: string
  description?: string
  trigger_stages?: string[]
  [key: string]: unknown
}

export interface RegisteredSkill {
  definition: SkillDefinition
  manifest_path: string
  content_hash: string
}

export interface SkillRegistrySnapshot {
  skill_count: number
  enabled_count: number
  mandatory_count: number
  source_digest: string
  skills: RegisteredSkill[]
}

export interface ApprovalItem {
  trace_id: string
  request_id: string
  tool_name?: string
  tool_args?: JsonObject
  [key: string]: unknown
}
