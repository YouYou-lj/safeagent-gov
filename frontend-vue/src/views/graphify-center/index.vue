<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { computed, onMounted, reactive, ref } from 'vue'

import { createGraphBuild, createGraphSearch, getGraphHealth, getGraphStats } from '@/api/governance'
import JsonViewer from '@/components/JsonViewer/index.vue'
import MetricGrid from '@/components/MetricGrid/index.vue'
import PageHeader from '@/components/PageHeader/index.vue'
import type { GraphHealth, GraphStats, JsonObject, MetricItem } from '@/types/api'

const loading = ref(false)
const building = ref(false)
const searching = ref(false)
const stats = ref<GraphStats | null>(null)
const health = ref<GraphHealth | null>(null)
const result = ref<JsonObject | null>(null)
const search = reactive({ query: '办理政务材料前检查提示词风险并读取公开政策', scenario: 'government_office', topK: 8, tokenBudget: 1200 })

const metrics = computed<MetricItem[]>(() => [
  { label: '节点', value: stats.value?.node_count ?? '—', detail: '任务、Skill、工具、策略、模型', tone: 'success' },
  { label: '关系', value: stats.value?.edge_count ?? '—', detail: '可追溯治理边', tone: 'success' },
  { label: '图谱健康', value: health.value?.healthy ? '通过' : '待检查', detail: health.value?.healthy ? '无缺失治理边界' : '存在健康告警', tone: health.value?.healthy ? 'success' : 'warning' },
  { label: '来源状态', value: health.value?.source_stale ? '已过期' : '同步', detail: '与可信清单内容哈希比对', tone: health.value?.source_stale ? 'danger' : 'success' },
])

async function loadGraph(): Promise<void> {
  loading.value = true
  try {
    ;[stats.value, health.value] = await Promise.all([getGraphStats(), getGraphHealth()])
  } finally {
    loading.value = false
  }
}

async function buildGraph(): Promise<void> {
  building.value = true
  try {
    result.value = await createGraphBuild()
    ElMessage.success('能力图谱已按可信清单重建')
    await loadGraph()
  } finally {
    building.value = false
  }
}

async function searchGraph(): Promise<void> {
  if (!search.query.trim()) return
  searching.value = true
  try {
    result.value = await createGraphSearch({
      query: search.query,
      scenario: search.scenario,
      top_k: search.topK,
      token_budget: search.tokenBudget,
    })
  } finally {
    searching.value = false
  }
}

onMounted(() => void loadGraph())
</script>

<template>
  <div class="safe-page">
    <PageHeader
      title="能力图谱"
      description="用结构化能力关系替代全量上下文拼接，为路由提供低 Token、可解释的候选路径。"
      refreshable
      :loading="loading"
      @refresh="loadGraph"
    >
      <template #actions>
        <el-button :loading="building" @click="buildGraph">
          重建可信图谱
        </el-button>
      </template>
    </PageHeader>
    <MetricGrid :items="metrics" />
    <section class="safe-grid--two graph-layout">
      <article class="safe-panel">
        <h2 class="safe-panel__title">
          能力检索
        </h2>
        <p class="safe-panel__subtitle">
          检索结果同时给出候选 Skill、工具、Agent、策略与 Token 节约证据。
        </p>
        <el-form label-position="top">
          <el-form-item label="任务意图">
            <el-input
              v-model="search.query"
              type="textarea"
              :rows="5"
              maxlength="50000"
              show-word-limit
            />
          </el-form-item>
          <div class="graph-form-row">
            <el-form-item label="场景">
              <el-select v-model="search.scenario">
                <el-option label="政务办公" value="government_office" />
                <el-option label="知识服务" value="knowledge_service" />
                <el-option label="流程办理" value="process_handling" />
                <el-option label="运维协同" value="operations_collaboration" />
              </el-select>
            </el-form-item>
            <el-form-item label="Top K">
              <el-input-number v-model="search.topK" :min="1" :max="50" />
            </el-form-item>
            <el-form-item label="Token 预算">
              <el-input-number
                v-model="search.tokenBudget"
                :min="200"
                :max="20000"
                :step="100"
              />
            </el-form-item>
          </div>
          <el-button type="primary" :loading="searching" @click="searchGraph">
            检索推荐路径
          </el-button>
        </el-form>
      </article>
      <article v-loading="searching || building" class="safe-panel">
        <h2 class="safe-panel__title">
          图谱证据
        </h2>
        <JsonViewer :value="result" empty-text="检索或重建后查看结构化结果。" />
      </article>
    </section>
  </div>
</template>

<style scoped lang="scss">
.graph-layout { grid-template-columns: minmax(360px, 0.82fr) minmax(0, 1.18fr); }
.graph-form-row { display: grid; grid-template-columns: 1.2fr 0.8fr 1fr; gap: 12px; }

@media (max-width: 1080px) {
  .graph-layout { grid-template-columns: 1fr; }
}

@media (max-width: 620px) {
  .graph-form-row { grid-template-columns: 1fr; }
}
</style>
