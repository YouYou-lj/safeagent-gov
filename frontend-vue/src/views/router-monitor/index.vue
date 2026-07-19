<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'

import { createRouterPlan } from '@/api/governance'
import { getTasks } from '@/api/tasks'
import JsonViewer from '@/components/JsonViewer/index.vue'
import PageHeader from '@/components/PageHeader/index.vue'
import StatusBadge from '@/components/StatusBadge/index.vue'
import type { JsonObject, TaskRecord } from '@/types/api'
import { formatTimestamp } from '@/utils/data'

const planning = ref(false)
const loadingTasks = ref(false)
const plan = ref<JsonObject | null>(null)
const tasks = ref<TaskRecord[]>([])
const form = reactive({
  task: '核验政务材料，先执行输入安全检查，再并行完成政策检索和材料完整性检查。',
  scenario: 'process_handling',
  parallel: true,
  maxAgents: 6,
  tokenBudget: 1200,
})

async function createPlan(): Promise<void> {
  planning.value = true
  try {
    plan.value = await createRouterPlan({
      task: form.task,
      scenario: form.scenario,
      enable_parallel_agents: form.parallel,
      max_sub_agents: form.maxAgents,
      token_budget: form.tokenBudget,
    })
  } finally {
    planning.value = false
  }
}

async function loadTasks(): Promise<void> {
  loadingTasks.value = true
  try {
    tasks.value = await getTasks(50)
  } finally {
    loadingTasks.value = false
  }
}

onMounted(() => void loadTasks())
</script>

<template>
  <div class="safe-page">
    <PageHeader
      title="路由监控"
      description="验证强制前置安全检查、子 Agent 扇出/汇聚以及隔离任务池的运行状态。"
      refreshable
      :loading="loadingTasks"
      @refresh="loadTasks"
    />
    <section class="safe-grid--two router-layout">
      <article class="safe-panel">
        <h2 class="safe-panel__title">
          SafeRouter 计划
        </h2>
        <el-form label-position="top">
          <el-form-item label="任务">
            <el-input v-model="form.task" type="textarea" :rows="4" />
          </el-form-item>
          <div class="router-form-row">
            <el-form-item label="场景">
              <el-select v-model="form.scenario">
                <el-option label="政务办公" value="government_office" />
                <el-option label="知识服务" value="knowledge_service" />
                <el-option label="流程办理" value="process_handling" />
                <el-option label="运维协同" value="operations_collaboration" />
              </el-select>
            </el-form-item>
            <el-form-item label="最大子 Agent">
              <el-input-number v-model="form.maxAgents" :min="2" :max="16" />
            </el-form-item>
            <el-form-item label="并行">
              <el-switch v-model="form.parallel" />
            </el-form-item>
          </div>
          <el-button type="primary" :loading="planning" @click="createPlan">
            生成受控路由计划
          </el-button>
        </el-form>
      </article>
      <article v-loading="planning" class="safe-panel">
        <h2 class="safe-panel__title">
          计划证据
        </h2>
        <JsonViewer :value="plan" empty-text="生成后展示强制 Skill、工具守卫、子任务 DAG 与图谱版本。" />
      </article>
    </section>
    <section class="safe-panel">
      <h2 class="safe-panel__title">
        当前租户任务
      </h2>
      <el-table v-loading="loadingTasks" :data="tasks" empty-text="暂无任务">
        <el-table-column prop="task_id" label="任务 ID" min-width="190" />
        <el-table-column prop="pool" label="隔离池" width="110" />
        <el-table-column prop="kind" label="类型" width="130" />
        <el-table-column prop="priority" label="优先级" width="100" />
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
.router-layout { grid-template-columns: minmax(360px, 0.85fr) minmax(0, 1.15fr); }
.router-form-row { display: grid; grid-template-columns: 1.4fr 1fr 0.6fr; gap: 12px; }

@media (max-width: 1080px) {
  .router-layout { grid-template-columns: 1fr; }
}

@media (max-width: 620px) {
  .router-form-row { grid-template-columns: 1fr; }
}
</style>
