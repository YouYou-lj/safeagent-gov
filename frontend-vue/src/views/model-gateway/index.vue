<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { computed, onMounted, reactive, ref } from 'vue'

import { createModelChat, getModelMetrics, getModelProviders } from '@/api/governance'
import JsonViewer from '@/components/JsonViewer/index.vue'
import MetricGrid from '@/components/MetricGrid/index.vue'
import PageHeader from '@/components/PageHeader/index.vue'
import StatusBadge from '@/components/StatusBadge/index.vue'
import type { JsonObject, MetricItem, ModelRegistrySnapshot } from '@/types/api'
import { readNumber } from '@/utils/data'

const loading = ref(false)
const chatting = ref(false)
const registry = ref<ModelRegistrySnapshot | null>(null)
const runtimeMetrics = ref<JsonObject | null>(null)
const response = ref<JsonObject | null>(null)
const form = reactive({
  prompt: '请以 JSON 说明当前请求不会获得工具执行权限。',
  provider: '',
  taskType: 'general',
  classification: 'internal',
  privateOnly: false,
  allowFallback: true,
  maxOutputTokens: 512,
  maxCostUsd: 0.1,
})

const metrics = computed<MetricItem[]>(() => [
  { label: 'Provider 配置', value: registry.value?.provider_count ?? '—', detail: '统一协议注册表', tone: 'success' },
  { label: '默认启用', value: registry.value?.enabled_count ?? '—', detail: '远端默认关闭', tone: 'success' },
  { label: '成功请求', value: readNumber(runtimeMetrics.value, 'successful_requests'), detail: '统一归一化输出' },
  { label: '缓存命中', value: readNumber(runtimeMetrics.value, 'cache_hits'), detail: '租户与身份隔离缓存' },
])

async function loadGateway(): Promise<void> {
  loading.value = true
  try {
    ;[registry.value, runtimeMetrics.value] = await Promise.all([getModelProviders(), getModelMetrics()])
  } finally {
    loading.value = false
  }
}

async function chat(): Promise<void> {
  if (!form.prompt.trim()) {
    ElMessage.warning('请输入模型请求')
    return
  }
  chatting.value = true
  try {
    const payload: JsonObject = {
      messages: [{ role: 'user', content: form.prompt }],
      task_type: form.taskType,
      max_output_tokens: form.maxOutputTokens,
      temperature: 0,
      required_capabilities: ['chat'],
      data_classification: form.classification,
      private_only: form.privateOnly,
      allow_fallback: form.allowFallback,
      cache_enabled: true,
      max_cost_usd: form.maxCostUsd,
    }
    if (form.provider) payload.requested_provider = form.provider
    response.value = await createModelChat(payload)
    ElMessage.success('调用完成；输出仍标记为不可信数据')
    await loadGateway()
  } finally {
    chatting.value = false
  }
}

onMounted(() => void loadGateway())
</script>

<template>
  <div class="safe-page">
    <PageHeader
      title="模型网关"
      description="统一管理多模型协议、数据分级、成本预算、缓存、降级和熔断；模型输出不具备执行权。"
      refreshable
      :loading="loading"
      @refresh="loadGateway"
    />
    <MetricGrid :items="metrics" />
    <section class="safe-panel">
      <h2 class="safe-panel__title">
        Provider 注册表
      </h2>
      <p class="safe-panel__subtitle">
        配置只记录凭据环境变量名，不在前端或仓库暴露密钥与端点敏感参数。
      </p>
      <el-table v-loading="loading" :data="registry?.providers ?? []" empty-text="暂无 Provider">
        <el-table-column prop="display_name" label="Provider" min-width="160" />
        <el-table-column prop="model" label="模型" min-width="150" />
        <el-table-column prop="protocol" label="协议" min-width="180" />
        <el-table-column label="部署" width="100">
          <template #default="scope">
            {{ scope.row.private_deployment ? '私有' : '远端' }}
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="scope">
            <StatusBadge :status="scope.row.enabled ? 'enabled' : 'disabled'" />
          </template>
        </el-table-column>
        <el-table-column label="能力" min-width="210">
          <template #default="scope">
            {{ scope.row.capabilities.join(' / ') }}
          </template>
        </el-table-column>
      </el-table>
    </section>
    <section class="safe-grid--two model-layout">
      <article class="safe-panel">
        <h2 class="safe-panel__title">
          受控调用
        </h2>
        <el-form label-position="top">
          <el-form-item label="用户消息">
            <el-input v-model="form.prompt" type="textarea" :rows="5" />
          </el-form-item>
          <div class="model-form-grid">
            <el-form-item label="Provider（空为自动路由）">
              <el-select v-model="form.provider" clearable filterable>
                <el-option
                  v-for="item in registry?.providers ?? []"
                  :key="item.provider_id"
                  :label="item.display_name"
                  :value="item.provider_id"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="数据分级">
              <el-select v-model="form.classification">
                <el-option label="公开 public" value="public" />
                <el-option label="内部 internal" value="internal" />
                <el-option label="机密 confidential" value="confidential" />
                <el-option label="受限 restricted" value="restricted" />
              </el-select>
            </el-form-item>
            <el-form-item label="成本上限（USD）">
              <el-input-number
                v-model="form.maxCostUsd"
                :min="0"
                :max="100"
                :precision="3"
              />
            </el-form-item>
            <el-form-item label="仅私有部署">
              <el-switch v-model="form.privateOnly" />
            </el-form-item>
          </div>
          <el-button type="primary" :loading="chatting" @click="chat">
            通过网关调用
          </el-button>
        </el-form>
      </article>
      <article v-loading="chatting" class="safe-panel">
        <h2 class="safe-panel__title">
          归一化响应
        </h2>
        <p class="safe-panel__subtitle">
          响应中的 output_trusted 必须为 false，任何动作需再次经过独立工具策略。
        </p>
        <JsonViewer :value="response" empty-text="提交请求后查看路由、用量、成本、缓存、降级与审计状态。" />
      </article>
    </section>
  </div>
</template>

<style scoped lang="scss">
.model-layout { grid-template-columns: minmax(360px, 0.9fr) minmax(0, 1.1fr); }
.model-form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 14px; }

@media (max-width: 1080px) {
  .model-layout { grid-template-columns: 1fr; }
}

@media (max-width: 620px) {
  .model-form-grid { grid-template-columns: 1fr; }
}
</style>
