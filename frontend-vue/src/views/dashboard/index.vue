<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { getGraphHealth, getGraphStats, getModelMetrics } from '@/api/governance'
import { getHealth } from '@/api/system'
import { getTaskMetrics, getTasks } from '@/api/tasks'
import MetricGrid from '@/components/MetricGrid/index.vue'
import PageHeader from '@/components/PageHeader/index.vue'
import StatusBadge from '@/components/StatusBadge/index.vue'
import type { GraphHealth, GraphStats, HealthResponse, JsonObject, MetricItem, TaskRecord, TaskRuntimeMetrics } from '@/types/api'
import { formatTimestamp, readNumber } from '@/utils/data'

const loading = ref(false)
const health = ref<HealthResponse | null>(null)
const graphHealth = ref<GraphHealth | null>(null)
const graphStats = ref<GraphStats | null>(null)
const taskMetrics = ref<TaskRuntimeMetrics | null>(null)
const modelMetrics = ref<JsonObject | null>(null)
const tasks = ref<TaskRecord[]>([])
const failedSections = ref<string[]>([])

const metrics = computed<MetricItem[]>(() => [
  {
    label: '能力图谱节点',
    value: graphStats.value?.node_count ?? '—',
    detail: `${graphStats.value?.edge_count ?? 0} 条治理关系`,
    tone: graphHealth.value?.healthy ? 'success' : 'warning',
  },
  {
    label: '异步任务成功',
    value: taskMetrics.value?.succeeded ?? '—',
    detail: `${taskMetrics.value?.mode ?? '未知模式'} / ${taskMetrics.value?.recovered ?? 0} 次恢复`,
    tone: (taskMetrics.value?.failed ?? 0) > 0 ? 'danger' : 'success',
  },
  {
    label: '模型网关请求',
    value: readNumber(modelMetrics.value, 'total_requests') || '—',
    detail: `${readNumber(modelMetrics.value, 'fallback_requests')} 次降级`,
    tone: readNumber(modelMetrics.value, 'failed_requests') > 0 ? 'warning' : 'success',
  },
  {
    label: '服务状态',
    value: health.value?.status ?? '未知',
    detail: health.value?.service ?? 'safeagent-gov',
    tone: health.value?.status === 'ok' || health.value?.status === 'healthy' ? 'success' : 'warning',
  },
])

async function loadDashboard(): Promise<void> {
  loading.value = true
  failedSections.value = []
  const results = await Promise.allSettled([
    getHealth(),
    getGraphHealth(),
    getGraphStats(),
    getTaskMetrics(),
    getModelMetrics(),
    getTasks(8),
  ])
  const labels = ['服务健康', '图谱健康', '图谱统计', '任务指标', '模型指标', '最近任务']
  results.forEach((result, index) => {
    if (result.status === 'rejected') failedSections.value.push(labels[index] ?? '未知模块')
  })
  if (results[0]?.status === 'fulfilled') health.value = results[0].value
  if (results[1]?.status === 'fulfilled') graphHealth.value = results[1].value
  if (results[2]?.status === 'fulfilled') graphStats.value = results[2].value
  if (results[3]?.status === 'fulfilled') taskMetrics.value = results[3].value
  if (results[4]?.status === 'fulfilled') modelMetrics.value = results[4].value
  if (results[5]?.status === 'fulfilled') tasks.value = results[5].value
  loading.value = false
}

onMounted(() => void loadDashboard())
</script>

<template>
  <div class="safe-page dashboard">
    <PageHeader
      title="安全总览"
      description="将能力图谱、异步任务、模型网关和审计运行态集中为一页可核验证据。"
      refreshable
      :loading="loading"
      @refresh="loadDashboard"
    />

    <el-alert
      v-if="failedSections.length"
      type="warning"
      :closable="false"
      show-icon
      :title="`部分证据未加载：${failedSections.join('、')}。请确认 Token 权限与后端状态。`"
    />

    <MetricGrid :items="metrics" />

    <section class="safe-grid--two">
      <article class="safe-panel">
        <h2 class="safe-panel__title">
          隔离执行池
        </h2>
        <p class="safe-panel__subtitle">
          安全、Agent 与评测任务采用独立容量和并发边界。
        </p>
        <el-table v-loading="loading" :data="taskMetrics?.pools ?? []" empty-text="暂无执行池指标">
          <el-table-column prop="pool" label="执行池" min-width="110" />
          <el-table-column prop="workers" label="Worker" width="90" />
          <el-table-column prop="queue_depth" label="队列深度" width="100" />
          <el-table-column prop="active_tasks" label="运行中" width="90" />
          <el-table-column prop="dead_letters" label="死信" width="80" />
          <el-table-column prop="queue_capacity" label="容量" width="90" />
        </el-table>
      </article>

      <article class="safe-panel">
        <h2 class="safe-panel__title">
          能力构成
        </h2>
        <p class="safe-panel__subtitle">
          Graphify-Gov 从仓库可信清单构建的节点类型分布。
        </p>
        <div v-if="graphStats" class="capability-list">
          <div v-for="(count, type) in graphStats.node_types" :key="type" class="capability-list__item">
            <span>{{ type }}</span><strong>{{ count }}</strong>
          </div>
        </div>
        <div v-else class="safe-empty">
          暂无图谱数据
        </div>
      </article>
    </section>

    <section class="safe-panel">
      <h2 class="safe-panel__title">
        最近异步任务
      </h2>
      <p class="safe-panel__subtitle">
        仅展示当前租户任务；任务正文不在总览页展开。
      </p>
      <el-table v-loading="loading" :data="tasks" empty-text="暂无任务记录">
        <el-table-column prop="task_id" label="任务 ID" min-width="190">
          <template #default="scope">
            <span class="safe-mono">{{ scope.row.task_id }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="kind" label="类型" width="130" />
        <el-table-column prop="priority" label="优先级" width="100" />
        <el-table-column prop="delivery_count" label="投递" width="76" />
        <el-table-column prop="recovered_count" label="恢复" width="76" />
        <el-table-column label="状态" width="120">
          <template #default="scope">
            <StatusBadge :status="scope.row.status" />
          </template>
        </el-table-column>
        <el-table-column label="更新时间" min-width="180">
          <template #default="scope">
            {{ formatTimestamp(scope.row.updated_at) }}
          </template>
        </el-table-column>
      </el-table>
    </section>
  </div>
</template>

<style scoped lang="scss">
.capability-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;

  &__item {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 12px;
    border: 1px solid var(--safe-color-border);
    border-radius: var(--safe-radius-control);
    background: var(--safe-color-surface-muted);

    span { color: var(--safe-color-text-secondary); font-size: 12px; }
    strong { font-family: var(--safe-font-mono); }
  }
}

@media (max-width: 560px) {
  .capability-list { grid-template-columns: 1fr; }
}
</style>
