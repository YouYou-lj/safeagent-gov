<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { ref } from 'vue'

import { getAuditTrace, getAuditVerification } from '@/api/governance'
import JsonViewer from '@/components/JsonViewer/index.vue'
import PageHeader from '@/components/PageHeader/index.vue'
import type { JsonObject } from '@/types/api'

const traceId = ref('')
const loading = ref(false)
const trace = ref<JsonObject | null>(null)
const verification = ref<JsonObject | null>(null)

async function queryTrace(): Promise<void> {
  if (!traceId.value.trim()) {
    ElMessage.warning('请输入 Trace ID')
    return
  }
  loading.value = true
  try {
    const [traceResult, verifyResult] = await Promise.all([
      getAuditTrace(traceId.value.trim()),
      getAuditVerification(traceId.value.trim()),
    ])
    trace.value = traceResult
    verification.value = verifyResult
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="safe-page">
    <PageHeader title="审计追踪" description="按 Trace 读取当前身份可见的事件视图，并独立验证哈希链完整性。" />
    <section class="trace-query safe-panel">
      <div>
        <h2 class="safe-panel__title">
          Trace 查询
        </h2>
        <p class="safe-panel__subtitle">
          租户隔离和字段脱敏由服务端根据签名身份执行。
        </p>
      </div>
      <el-input
        v-model="traceId"
        clearable
        placeholder="例如 TRACE-..."
        @keyup.enter="queryTrace"
      >
        <template #append>
          <el-button :loading="loading" @click="queryTrace">
            查询并验链
          </el-button>
        </template>
      </el-input>
    </section>
    <section class="safe-grid--two audit-layout">
      <article v-loading="loading" class="safe-panel">
        <h2 class="safe-panel__title">
          事件链
        </h2>
        <JsonViewer :value="trace" empty-text="输入 Trace ID 查看任务、风险、Skill、工具与最终输出事件。" />
      </article>
      <article v-loading="loading" class="safe-panel">
        <h2 class="safe-panel__title">
          完整性验证
        </h2>
        <p class="safe-panel__subtitle">
          验证事件序号、prev_hash 和 event_hash 的连续性。
        </p>
        <JsonViewer :value="verification" empty-text="验链结果将在此展示。" />
      </article>
    </section>
  </div>
</template>

<style scoped lang="scss">
.trace-query {
  display: grid;
  grid-template-columns: minmax(240px, 0.6fr) minmax(300px, 1.4fr);
  gap: 24px;
  align-items: center;
}

.audit-layout { grid-template-columns: minmax(0, 1.25fr) minmax(300px, 0.75fr); align-items: start; }

@media (max-width: 920px) {
  .trace-query,
  .audit-layout { grid-template-columns: 1fr; }
}
</style>
