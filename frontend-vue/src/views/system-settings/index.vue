<script setup lang="ts">
import { ElMessage, ElMessageBox } from 'element-plus'
import { onMounted, reactive, ref } from 'vue'

import {
  createPolicyCanary,
  createPolicyPromotion,
  createPolicyRollback,
  getGraphHealth,
} from '@/api/governance'
import { getAuthIdentity, getPolicyStatus } from '@/api/system'
import JsonViewer from '@/components/JsonViewer/index.vue'
import PageHeader from '@/components/PageHeader/index.vue'
import type { JsonObject } from '@/types/api'

const loading = ref(false)
const changing = ref(false)
const identity = ref<JsonObject | null>(null)
const policy = ref<JsonObject | null>(null)
const graphHealth = ref<JsonObject | null>(null)
const lastChange = ref<JsonObject | null>(null)
const canary = reactive({ version: '1.1.0', percent: 10 })

async function loadSettings(): Promise<void> {
  loading.value = true
  try {
    ;[identity.value, policy.value, graphHealth.value] = await Promise.all([
      getAuthIdentity(),
      getPolicyStatus(),
      getGraphHealth(),
    ])
  } finally {
    loading.value = false
  }
}

async function configureCanary(): Promise<void> {
  changing.value = true
  try {
    lastChange.value = await createPolicyCanary(canary.version, canary.percent)
    ElMessage.success('灰度策略已配置并写入审计链')
    await loadSettings()
  } finally {
    changing.value = false
  }
}

async function confirmChange(kind: 'promote' | 'rollback'): Promise<void> {
  const action = kind === 'promote' ? '全量发布灰度版本' : '回滚到上一稳定版本'
  await ElMessageBox.confirm(`${action}会改变后端工具裁决策略，且操作将写入合规审计。`, action, {
    type: 'warning',
    confirmButtonText: '确认执行',
    cancelButtonText: '取消',
  })
  changing.value = true
  try {
    lastChange.value = kind === 'promote' ? await createPolicyPromotion() : await createPolicyRollback()
    ElMessage.success(`${action}完成`)
    await loadSettings()
  } finally {
    changing.value = false
  }
}

onMounted(() => void loadSettings())
</script>

<template>
  <div class="safe-page">
    <PageHeader
      title="系统治理"
      description="核验当前签名身份、策略发布状态和图谱健康，并以审计化流程执行策略变更。"
      refreshable
      :loading="loading"
      @refresh="loadSettings"
    />
    <section class="safe-grid--two settings-summary">
      <article v-loading="loading" class="safe-panel">
        <h2 class="safe-panel__title">
          服务端身份视图
        </h2>
        <p class="safe-panel__subtitle">
          此处展示服务端验签后的 Claims，不以浏览器本地解码结果作为授权依据。
        </p>
        <JsonViewer :value="identity" />
      </article>
      <article v-loading="loading" class="safe-panel">
        <h2 class="safe-panel__title">
          能力图谱健康
        </h2>
        <JsonViewer :value="graphHealth" />
      </article>
    </section>
    <section class="policy-layout">
      <article v-loading="loading" class="safe-panel">
        <h2 class="safe-panel__title">
          工具策略发布状态
        </h2>
        <JsonViewer :value="policy" empty-text="暂无策略状态。" />
      </article>
      <article class="safe-panel">
        <h2 class="safe-panel__title">
          审计化发布控制
        </h2>
        <p class="safe-panel__subtitle">
          仅 admin / security_reviewer 可执行；灰度版本必须已存在于可信策略目录。
        </p>
        <el-form label-position="top">
          <el-form-item label="目标版本">
            <el-input v-model="canary.version" placeholder="例如 1.1.0" />
          </el-form-item>
          <el-form-item label="灰度比例">
            <el-slider
              v-model="canary.percent"
              :min="1"
              :max="100"
              show-input
            />
          </el-form-item>
          <div class="safe-form-actions">
            <el-button :loading="changing" @click="configureCanary">
              配置灰度
            </el-button>
            <el-button type="primary" :loading="changing" @click="confirmChange('promote')">
              发布灰度版本
            </el-button>
            <el-button
              type="danger"
              plain
              :loading="changing"
              @click="confirmChange('rollback')"
            >
              回滚稳定版本
            </el-button>
          </div>
        </el-form>
      </article>
    </section>
    <section v-if="lastChange" class="safe-panel">
      <h2 class="safe-panel__title">
        最近变更回执
      </h2>
      <JsonViewer :value="lastChange" />
    </section>
  </div>
</template>

<style scoped lang="scss">
.settings-summary { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.policy-layout { display: grid; grid-template-columns: minmax(0, 1.2fr) minmax(340px, 0.8fr); gap: 16px; align-items: start; }

@media (max-width: 980px) {
  .settings-summary,
  .policy-layout { grid-template-columns: 1fr; }
}
</style>
