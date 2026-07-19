<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { onMounted, ref } from 'vue'

import { createEvaluation, getEvaluationResults } from '@/api/governance'
import JsonViewer from '@/components/JsonViewer/index.vue'
import PageHeader from '@/components/PageHeader/index.vue'
import type { JsonObject } from '@/types/api'

const loading = ref(false)
const running = ref(false)
const evalType = ref('all')
const results = ref<JsonObject | null>(null)
const runReceipt = ref<JsonObject | null>(null)

async function loadResults(): Promise<void> {
  loading.value = true
  try {
    results.value = await getEvaluationResults()
  } finally {
    loading.value = false
  }
}

async function runEvaluation(): Promise<void> {
  running.value = true
  try {
    runReceipt.value = await createEvaluation(evalType.value)
    ElMessage.success('评测完成，结果已写入本地证据目录')
    await loadResults()
  } finally {
    running.value = false
  }
}

onMounted(() => void loadResults())
</script>

<template>
  <div class="safe-page">
    <PageHeader
      title="安全评测"
      description="以固定数据集量化提示词防护、工具治理、Skill 扫描和审计链完整性。"
      refreshable
      :loading="loading"
      @refresh="loadResults"
    >
      <template #actions>
        <el-select v-model="evalType" class="eval-selector">
          <el-option label="全部评测" value="all" />
          <el-option label="提示词安全" value="prompt" />
          <el-option label="工具治理" value="tool" />
          <el-option label="Skill 扫描" value="skill" />
          <el-option label="审计链" value="audit" />
        </el-select>
        <el-button type="primary" :loading="running" @click="runEvaluation">
          运行评测
        </el-button>
      </template>
    </PageHeader>
    <el-alert
      type="info"
      :closable="false"
      show-icon
      title="评测任务在后端受 RBAC 保护；生产环境建议通过异步 evaluation 隔离池执行耗时任务。"
    />
    <section class="safe-grid--two eval-layout">
      <article v-loading="loading" class="safe-panel">
        <h2 class="safe-panel__title">
          最新指标证据
        </h2>
        <JsonViewer :value="results" empty-text="当前没有可读取的评测结果。" />
      </article>
      <article v-loading="running" class="safe-panel">
        <h2 class="safe-panel__title">
          本次运行回执
        </h2>
        <p class="safe-panel__subtitle">
          仅展示后端实际返回结果，不使用前端模拟分数。
        </p>
        <JsonViewer :value="runReceipt" empty-text="选择评测类型并运行后查看回执。" />
      </article>
    </section>
  </div>
</template>

<style scoped lang="scss">
.eval-selector { width: 150px; }
.eval-layout { grid-template-columns: minmax(0, 1.25fr) minmax(300px, 0.75fr); align-items: start; }

@media (max-width: 960px) {
  .eval-layout { grid-template-columns: 1fr; }
}
</style>
