<script setup lang="ts">
import { ElMessage, ElMessageBox } from 'element-plus'
import { onMounted, ref } from 'vue'

import { createApproval, getPendingApprovals } from '@/api/governance'
import JsonViewer from '@/components/JsonViewer/index.vue'
import PageHeader from '@/components/PageHeader/index.vue'
import type { ApprovalItem, JsonObject } from '@/types/api'

const loading = ref(false)
const deciding = ref(false)
const approvals = ref<ApprovalItem[]>([])
const selected = ref<ApprovalItem | null>(null)
const lastDecision = ref<JsonObject | null>(null)

async function loadApprovals(): Promise<void> {
  loading.value = true
  try {
    approvals.value = (await getPendingApprovals()).items
    if (selected.value && !approvals.value.some((item) => item.request_id === selected.value?.request_id)) selected.value = null
  } finally {
    loading.value = false
  }
}

async function decide(decision: 'allow' | 'deny'): Promise<void> {
  if (!selected.value) return
  const action = decision === 'allow' ? '批准' : '拒绝'
  const { value: comment } = await ElMessageBox.prompt(`请输入${action}理由，决定将写入不可变审计链。`, `${action}工具调用`, {
    inputPattern: /\S+/,
    inputErrorMessage: '必须填写审批理由',
    confirmButtonText: `确认${action}`,
    cancelButtonText: '取消',
    type: decision === 'allow' ? 'warning' : 'error',
  })
  deciding.value = true
  try {
    lastDecision.value = await createApproval({
      trace_id: selected.value.trace_id,
      request_id: selected.value.request_id,
      decision,
      comment,
      masked_args: {},
    })
    ElMessage.success(`已${action}，审计证据已记录`)
    selected.value = null
    await loadApprovals()
  } finally {
    deciding.value = false
  }
}

onMounted(() => void loadApprovals())
</script>

<template>
  <div class="safe-page">
    <PageHeader
      title="审批中心"
      description="高风险工具调用默认暂停，由具备权限的复核角色作出可追溯决定。"
      refreshable
      :loading="loading"
      @refresh="loadApprovals"
    />
    <el-alert
      type="warning"
      :closable="false"
      show-icon
      title="批准只会记录授权决定；实际恢复还必须携带一次性 capability ticket，防止审批结果被重放。"
    />
    <section class="approval-layout">
      <article class="safe-panel">
        <h2 class="safe-panel__title">
          待处理请求
        </h2>
        <el-table
          v-loading="loading"
          :data="approvals"
          highlight-current-row
          empty-text="当前没有待审批请求"
          @current-change="selected = $event"
        >
          <el-table-column prop="tool_name" label="工具" min-width="130" />
          <el-table-column prop="request_id" label="请求 ID" min-width="160" />
          <el-table-column prop="trace_id" label="Trace ID" min-width="180" />
        </el-table>
      </article>
      <article class="safe-panel">
        <div class="approval-heading">
          <div>
            <h2 class="safe-panel__title">
              请求详情
            </h2>
            <p class="safe-panel__subtitle">
              核验工具参数、身份与上下文后再决定。
            </p>
          </div>
          <div class="safe-form-actions">
            <el-button
              type="danger"
              plain
              :disabled="!selected"
              :loading="deciding"
              @click="decide('deny')"
            >
              拒绝
            </el-button>
            <el-button
              type="primary"
              :disabled="!selected"
              :loading="deciding"
              @click="decide('allow')"
            >
              批准
            </el-button>
          </div>
        </div>
        <JsonViewer :value="selected" empty-text="从左侧选择待审批请求。" />
      </article>
    </section>
    <section v-if="lastDecision" class="safe-panel">
      <h2 class="safe-panel__title">
        最近审批回执
      </h2>
      <JsonViewer :value="lastDecision" />
    </section>
  </div>
</template>

<style scoped lang="scss">
.approval-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.1fr) minmax(340px, 0.9fr);
  gap: 16px;
  align-items: start;
}

.approval-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

@media (max-width: 1040px) {
  .approval-layout { grid-template-columns: 1fr; }
}
</style>
