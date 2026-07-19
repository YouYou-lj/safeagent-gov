<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { reactive, ref } from 'vue'

import { createToolCheck } from '@/api/governance'
import JsonViewer from '@/components/JsonViewer/index.vue'
import PageHeader from '@/components/PageHeader/index.vue'
import type { JsonObject } from '@/types/api'

const checking = ref(false)
const result = ref<JsonObject | null>(null)
const form = reactive({
  toolName: 'file_read',
  argsText: '{\n  "path": "agent_demo/data/public/政策问答示例.txt"\n}',
})

async function checkTool(): Promise<void> {
  let toolArgs: JsonObject
  try {
    const parsed: unknown = JSON.parse(form.argsText)
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) throw new Error('invalid')
    toolArgs = parsed as JsonObject
  } catch {
    ElMessage.warning('工具参数必须是合法 JSON 对象')
    return
  }
  checking.value = true
  try {
    result.value = await createToolCheck({ tool_name: form.toolName, tool_args: toolArgs, context: {} })
    ElMessage.success('策略裁决完成，未自动执行工具')
  } finally {
    checking.value = false
  }
}
</script>

<template>
  <div class="safe-page">
    <PageHeader title="MCP 网关" description="在执行前验证工具、参数、身份与风险策略；高风险动作必须进入人工审批。">
      <template #actions>
        <el-button type="primary" :loading="checking" @click="checkTool">
          执行策略检查
        </el-button>
      </template>
    </PageHeader>
    <el-alert
      type="info"
      :closable="false"
      show-icon
      title="此页面只调用 /api/tool/check 生成裁决，不会绕过审批直接执行工具。"
    />
    <section class="safe-grid--two">
      <article class="safe-panel">
        <h2 class="safe-panel__title">
          调用意图
        </h2>
        <el-form label-position="top">
          <el-form-item label="工具名称">
            <el-select
              v-model="form.toolName"
              filterable
              allow-create
              default-first-option
              class="mcp-control"
            >
              <el-option label="读取文件 file_read" value="file_read" />
              <el-option label="写入文件 file_write" value="file_write" />
              <el-option label="发送邮件 send_email" value="send_email" />
              <el-option label="数据库查询 db_query" value="db_query" />
              <el-option label="Shell 命令 shell_exec" value="shell_exec" />
            </el-select>
          </el-form-item>
          <el-form-item label="参数 JSON">
            <el-input
              v-model="form.argsText"
              type="textarea"
              :rows="14"
              resize="vertical"
            />
          </el-form-item>
        </el-form>
      </article>
      <article v-loading="checking" class="safe-panel">
        <h2 class="safe-panel__title">
          裁决证据
        </h2>
        <p class="safe-panel__subtitle">
          结果包含 Trace、请求 ID、策略版本、决策和需要时生成的审批 ID。
        </p>
        <JsonViewer :value="result" empty-text="提交工具意图后查看 allow、deny、mask 或 require_approval 裁决。" />
      </article>
    </section>
  </div>
</template>

<style scoped lang="scss">
.mcp-control { width: 100%; }
</style>
