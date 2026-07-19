<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { reactive, ref } from 'vue'

import { createAgentInspection, type WorkbenchResult } from '@/api/workbench'
import JsonViewer from '@/components/JsonViewer/index.vue'

const scenarios = [
  { value: 'government_office', label: '政务办公' },
  { value: 'knowledge_service', label: '知识服务' },
  { value: 'process_handling', label: '流程办理' },
  { value: 'operations_collaboration', label: '运维协同' },
]
const isRunning = ref(false)
const result = ref<WorkbenchResult | null>(null)
const form = reactive({
  scenario: 'government_office',
  task: '读取公开政策材料，生成不包含个人敏感信息的办事摘要。',
  documentText: '',
  documentSource: 'uploaded_doc',
})

async function handleRun(): Promise<void> {
  if (!form.task.trim()) {
    ElMessage.warning('请输入 Agent 测试任务')
    return
  }
  isRunning.value = true
  try {
    result.value = await createAgentInspection({
      task: form.task,
      scenario: form.scenario,
      document_text: form.documentText,
      document_source: form.documentSource,
    })
    ElMessage.success('Agent 安全路由测试完成，已生成可审计 Trace')
  } finally {
    isRunning.value = false
  }
}
</script>

<template>
  <section class="agent-inspector">
    <article class="agent-inspector__input">
      <div class="agent-inspector__heading">
        <div>
          <h2>多路由 Agent 测试</h2>
          <p>复用 Graphify、SafeRouter、强制 Skill 与 MCPGuard，不建立旁路执行链。</p>
        </div>
        <el-tag type="success" effect="plain">
          完整治理链
        </el-tag>
      </div>
      <el-form label-position="top">
        <el-form-item label="业务场景">
          <el-select v-model="form.scenario" class="agent-inspector__control">
            <el-option
              v-for="scenario in scenarios"
              :key="scenario.value"
              :label="scenario.label"
              :value="scenario.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="任务描述">
          <el-input
            v-model="form.task"
            type="textarea"
            :rows="6"
            maxlength="50000"
            show-word-limit
          />
        </el-form-item>
        <el-form-item label="附加不可信文档（可选）">
          <el-input
            v-model="form.documentText"
            type="textarea"
            :rows="7"
            maxlength="100000"
            show-word-limit
            placeholder="粘贴需要一并检测的外部文档"
          />
        </el-form-item>
        <el-form-item label="文档来源">
          <el-input v-model="form.documentSource" maxlength="160" />
        </el-form-item>
        <el-button type="primary" :loading="isRunning" @click="handleRun">
          运行安全路由测试
        </el-button>
      </el-form>
    </article>
    <article v-loading="isRunning" class="agent-inspector__result">
      <div class="agent-inspector__heading">
        <div>
          <h2>路由链与执行证据</h2>
          <p>查看输入风险、RouterPlan、子 Agent、Skill 覆盖、工具裁决和最终输出。</p>
        </div>
        <el-tag v-if="result?.trace_id" type="success" effect="light">
          Trace 已生成
        </el-tag>
      </div>
      <JsonViewer :value="result" empty-text="运行任务后查看统一结构化证据。" />
    </article>
  </section>
</template>

<style lang="scss" scoped>
.agent-inspector {
  display: grid;
  grid-template-columns: minmax(340px, 0.82fr) minmax(0, 1.18fr);
  gap: 16px;
  padding-top: 8px;

  &__input,
  &__result {
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

  &__control { width: 100%; }
}

@media (max-width: 980px) {
  .agent-inspector { grid-template-columns: 1fr; }
}
</style>
