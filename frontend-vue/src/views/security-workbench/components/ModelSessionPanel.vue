<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'

import {
  createEphemeralConnectionTest,
  createEphemeralModelChat,
  type DataClassification,
  type EphemeralProvider,
  type EphemeralProviderPayload,
  type WorkbenchResult,
} from '@/api/workbench'
import JsonViewer from '@/components/JsonViewer/index.vue'

interface ProviderOption {
  value: EphemeralProvider
  label: string
  defaultModel: string
  endpointHint: string
  isKeyRequired: boolean
  isPrivate: boolean
}

const DEFAULT_PROVIDER: ProviderOption = {
  value: 'openai',
  label: 'OpenAI Chat',
  defaultModel: 'gpt-4.1-mini',
  endpointHint: '固定为 OpenAI 官方 API',
  isKeyRequired: true,
  isPrivate: false,
}
const providerOptions: ProviderOption[] = [
  DEFAULT_PROVIDER,
  { value: 'openai-responses', label: 'OpenAI Responses', defaultModel: 'gpt-4.1-mini', endpointHint: '固定为 OpenAI 官方 Responses API', isKeyRequired: true, isPrivate: false },
  { value: 'anthropic', label: 'Anthropic', defaultModel: 'claude-sonnet-4-5', endpointHint: '固定为 Anthropic 官方 API', isKeyRequired: true, isPrivate: false },
  { value: 'gemini', label: 'Google Gemini', defaultModel: 'gemini-2.5-flash', endpointHint: '按模型生成 Google 官方 endpoint', isKeyRequired: true, isPrivate: false },
  { value: 'azure-openai', label: 'Azure OpenAI', defaultModel: 'deployment-name', endpointHint: '需填写组织 Azure deployment endpoint', isKeyRequired: true, isPrivate: true },
  { value: 'aws-bedrock', label: 'AWS Bedrock', defaultModel: 'model-id', endpointHint: '需填写组织 Bedrock invoke endpoint', isKeyRequired: true, isPrivate: true },
  { value: 'vertex-ai', label: 'Google Vertex AI', defaultModel: 'model-id', endpointHint: '需填写组织 Vertex generateContent endpoint', isKeyRequired: true, isPrivate: true },
  { value: 'deepseek', label: 'DeepSeek', defaultModel: 'deepseek-chat', endpointHint: '固定为 DeepSeek 官方 API', isKeyRequired: true, isPrivate: false },
  { value: 'qwen', label: '通义千问', defaultModel: 'qwen-plus', endpointHint: '固定为 DashScope 兼容 API', isKeyRequired: true, isPrivate: false },
  { value: 'kimi', label: 'Kimi', defaultModel: 'moonshot-v1-8k', endpointHint: '固定为 Moonshot 官方 API', isKeyRequired: true, isPrivate: false },
  { value: 'ollama', label: 'Ollama 本机', defaultModel: 'qwen3:8b', endpointHint: '仅允许 localhost / 127.0.0.1 的 /api/chat', isKeyRequired: false, isPrivate: true },
  { value: 'vllm', label: 'vLLM 本机', defaultModel: 'local-model', endpointHint: '仅允许 localhost / 127.0.0.1 的 /v1/chat/completions', isKeyRequired: false, isPrivate: true },
]

const isTesting = ref(false)
const isChatting = ref(false)
const connectionResult = ref<WorkbenchResult | null>(null)
const chatResult = ref<WorkbenchResult | null>(null)
const form = reactive({
  provider: 'openai' as EphemeralProvider,
  model: 'gpt-4.1-mini',
  endpoint: '',
  apiKey: '',
  timeoutSeconds: 15,
  prompt: '请说明你是一个不具备工具执行权的文本模型。',
  classification: 'public' as DataClassification,
  maxOutputTokens: 512,
})

const selectedProvider = computed(
  () => providerOptions.find((item) => item.value === form.provider) ?? DEFAULT_PROVIDER,
)
const canSendClassification = computed(
  () => selectedProvider.value.isPrivate || !['confidential', 'restricted'].includes(form.classification),
)

watch(
  () => form.provider,
  () => {
    form.model = selectedProvider.value.defaultModel
    form.endpoint = ''
    form.apiKey = ''
    connectionResult.value = null
    chatResult.value = null
  },
)

function createProviderPayload(): EphemeralProviderPayload {
  const payload: EphemeralProviderPayload = {
    provider: form.provider,
    model: form.model.trim(),
    timeout_seconds: form.timeoutSeconds,
  }
  if (form.endpoint.trim()) payload.endpoint = form.endpoint.trim()
  if (form.apiKey) payload.api_key = form.apiKey
  return payload
}

function validateProviderForm(): boolean {
  if (!form.model.trim()) {
    ElMessage.warning('请输入模型或 deployment 名称')
    return false
  }
  if (selectedProvider.value.isKeyRequired && !form.apiKey) {
    ElMessage.warning('请输入仅用于本次请求的 API Key')
    return false
  }
  return true
}

async function handleConnectionTest(): Promise<void> {
  if (!validateProviderForm()) return
  isTesting.value = true
  try {
    connectionResult.value = await createEphemeralConnectionTest(createProviderPayload())
    ElMessage.success('连接测试完成；凭据未持久化')
  } finally {
    isTesting.value = false
  }
}

async function handleChat(): Promise<void> {
  if (!validateProviderForm()) return
  if (!form.prompt.trim()) {
    ElMessage.warning('请输入测试消息')
    return
  }
  if (!canSendClassification.value) {
    ElMessage.warning('机密或受限数据只能发送到本机或组织私有 Provider')
    return
  }
  isChatting.value = true
  try {
    chatResult.value = await createEphemeralModelChat({
      ...createProviderPayload(),
      messages: [{ role: 'user', content: form.prompt }],
      max_output_tokens: form.maxOutputTokens,
      temperature: 0,
      data_classification: form.classification,
    })
    ElMessage.success('临时会话完成；输出保持不可信标记')
  } finally {
    isChatting.value = false
  }
}

onBeforeUnmount(() => {
  form.apiKey = ''
})
</script>

<template>
  <section class="model-session">
    <article class="model-session__configuration">
      <div class="model-session__heading">
        <div>
          <h2>一次性 Provider 配置</h2>
          <p>API Key 只进入当前请求内存，切换 Provider 或离开页面时立即清空。</p>
        </div>
        <el-tag type="warning" effect="plain">
          不持久化凭据
        </el-tag>
      </div>
      <el-form label-position="top">
        <div class="model-session__form-grid">
          <el-form-item label="Provider">
            <el-select v-model="form.provider" filterable>
              <el-option
                v-for="provider in providerOptions"
                :key="provider.value"
                :label="provider.label"
                :value="provider.value"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="模型 / Deployment">
            <el-input v-model="form.model" maxlength="200" />
          </el-form-item>
        </div>
        <el-form-item label="自定义 endpoint（仅 Azure、Bedrock、Vertex 或本机服务需要）">
          <el-input v-model="form.endpoint" maxlength="1000" :placeholder="selectedProvider.endpointHint" />
        </el-form-item>
        <el-form-item label="一次性 API Key">
          <el-input
            v-model="form.apiKey"
            type="password"
            show-password
            autocomplete="off"
            :placeholder="selectedProvider.isKeyRequired ? '仅保留在当前组件内存' : '本机服务可留空'"
          />
        </el-form-item>
        <div class="model-session__form-grid">
          <el-form-item label="超时（秒）">
            <el-input-number v-model="form.timeoutSeconds" :min="1" :max="30" />
          </el-form-item>
          <el-form-item label="数据分级">
            <el-select v-model="form.classification">
              <el-option label="公开 public" value="public" />
              <el-option label="内部 internal" value="internal" />
              <el-option label="机密 confidential" value="confidential" />
              <el-option label="受限 restricted" value="restricted" />
            </el-select>
          </el-form-item>
        </div>
        <el-alert
          v-if="!canSendClassification"
          class="model-session__classification-alert"
          type="warning"
          :closable="false"
          title="当前数据等级不能发送到公共远端 Provider。"
        />
        <el-form-item label="测试消息">
          <el-input
            v-model="form.prompt"
            type="textarea"
            :rows="5"
            maxlength="200000"
            show-word-limit
          />
        </el-form-item>
        <div class="model-session__actions">
          <el-button :loading="isTesting" @click="handleConnectionTest">
            测试连接
          </el-button>
          <el-button type="primary" :loading="isChatting" @click="handleChat">
            发送受治理消息
          </el-button>
        </div>
      </el-form>
    </article>
    <article class="model-session__evidence">
      <div class="model-session__heading">
        <div>
          <h2>通信与风险证据</h2>
          <p>连接与聊天均生成 Trace；模型输出会再次扫描且 output_trusted=false。</p>
        </div>
      </div>
      <el-tabs type="border-card">
        <el-tab-pane label="连接测试">
          <JsonViewer :value="connectionResult" empty-text="点击测试连接后查看协议归一与审计结果。" />
        </el-tab-pane>
        <el-tab-pane label="聊天响应">
          <JsonViewer :value="chatResult" empty-text="发送消息后查看输入风险、输出风险、用量和 Trace。" />
        </el-tab-pane>
      </el-tabs>
    </article>
  </section>
</template>

<style lang="scss" scoped>
.model-session {
  display: grid;
  grid-template-columns: minmax(370px, 0.9fr) minmax(0, 1.1fr);
  gap: 16px;
  padding-top: 8px;

  &__configuration,
  &__evidence {
    padding: 18px;
    border: 1px solid var(--safe-color-border);
    border-radius: var(--safe-radius-card);
    background: var(--safe-color-surface-muted);
  }

  &__heading {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 14px;
    margin-bottom: 16px;

    h2 { margin: 0; font-size: 16px; }
    p { margin: 7px 0 0; color: var(--safe-color-text-secondary); font-size: 12px; line-height: 1.6; }
  }

  &__form-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 14px;
  }

  &__classification-alert { margin-bottom: 16px; }

  &__actions {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
  }
}

@media (max-width: 1040px) {
  .model-session { grid-template-columns: 1fr; }
}

@media (max-width: 620px) {
  .model-session__form-grid { grid-template-columns: 1fr; gap: 0; }
}
</style>
