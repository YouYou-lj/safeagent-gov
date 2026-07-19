<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { reactive, ref } from 'vue'

import { createAgentRun } from '@/api/agent'
import JsonViewer from '@/components/JsonViewer/index.vue'
import PageHeader from '@/components/PageHeader/index.vue'
import type { JsonObject } from '@/types/api'
import { readString } from '@/utils/data'

const scenarios = [
  { value: 'government_office', label: '政务办公', note: '公文、会议纪要与受控邮件协同' },
  { value: 'knowledge_service', label: '知识服务', note: '政策检索、RAG 与来源可信度审查' },
  { value: 'process_handling', label: '流程办理', note: '材料核验、查询归档与人工审批' },
  { value: 'operations_collaboration', label: '运维协同', note: '运维查询、变更建议与高危命令阻断' },
]
const loading = ref(false)
const result = ref<JsonObject | null>(null)
const form = reactive({
  scenario: 'government_office',
  task: '读取公开政策材料，生成一份不包含个人敏感信息的办事摘要。',
  documentText: '',
  documentSource: 'uploaded_doc',
})

async function runAgent(): Promise<void> {
  if (!form.task.trim()) {
    ElMessage.warning('请输入演练任务')
    return
  }
  loading.value = true
  try {
    result.value = await createAgentRun({
      task: form.task,
      scenario: form.scenario,
      document_text: form.documentText,
      document_source: form.documentSource,
    })
    ElMessage.success('演练完成，已生成完整 Trace')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="safe-page">
    <PageHeader title="智能体演练" description="执行真实安全编排链，输出风险检测、路由、Skill、工具裁决和最终证据。">
      <template #actions>
        <el-button type="primary" :loading="loading" @click="runAgent">
          运行安全编排
        </el-button>
      </template>
    </PageHeader>

    <section class="playground-grid">
      <article class="safe-panel">
        <h2 class="safe-panel__title">
          任务输入
        </h2>
        <el-form label-position="top">
          <el-form-item label="政企场景">
            <el-select v-model="form.scenario" class="playground-grid__control">
              <el-option
                v-for="item in scenarios"
                :key="item.value"
                :value="item.value"
                :label="item.label"
              >
                <span>{{ item.label }}</span><small class="scenario-note">{{ item.note }}</small>
              </el-option>
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
          <el-form-item label="附加文档（可选、不可信输入）">
            <el-input
              v-model="form.documentText"
              type="textarea"
              :rows="7"
              maxlength="100000"
              show-word-limit
              placeholder="可粘贴待检测文档，系统会在 Agent 执行前进行内容安全检查"
            />
          </el-form-item>
          <el-form-item label="文档来源标识">
            <el-input v-model="form.documentSource" maxlength="160" />
          </el-form-item>
        </el-form>
      </article>

      <article v-loading="loading" class="safe-panel result-panel">
        <div class="result-panel__heading">
          <div>
            <h2 class="safe-panel__title">
              编排结果
            </h2>
            <p class="safe-panel__subtitle">
              模型输出始终作为不可信数据，工具执行权由 MCP-Guard 独立裁决。
            </p>
          </div>
          <el-tag v-if="result" type="success" effect="light">
            {{ readString(result, 'status') || 'completed' }}
          </el-tag>
        </div>
        <dl v-if="result" class="evidence-strip">
          <div><dt>Trace ID</dt><dd>{{ readString(result, 'trace_id') }}</dd></div>
          <div><dt>强制 Skill 覆盖率</dt><dd>{{ result.mandatory_skill_coverage ?? '—' }}</dd></div>
          <div><dt>ToolGuard 覆盖率</dt><dd>{{ result.toolguard_coverage ?? '—' }}</dd></div>
        </dl>
        <JsonViewer :value="result" empty-text="运行后将在此展示结构化证据，不会自动执行未经策略批准的动作。" />
      </article>
    </section>
  </div>
</template>

<style scoped lang="scss">
.playground-grid {
  display: grid;
  grid-template-columns: minmax(320px, 0.78fr) minmax(0, 1.22fr);
  gap: 18px;
  align-items: start;

  &__control { width: 100%; }
}

.scenario-note {
  margin-left: 12px;
  color: var(--safe-color-text-secondary);
}

.result-panel {
  position: sticky;
  top: calc(var(--safe-layout-header) + 20px);

  &__heading {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 16px;
  }
}

.evidence-strip {
  display: grid;
  grid-template-columns: 1.4fr 1fr 1fr;
  gap: 1px;
  margin: 0 0 16px;
  overflow: hidden;
  border: 1px solid var(--safe-color-border);
  border-radius: var(--safe-radius-control);
  background: var(--safe-color-border);

  div { min-width: 0; padding: 12px; background: var(--safe-color-surface-muted); }
  dt { color: var(--safe-color-text-secondary); font-size: 11px; }
  dd { margin: 5px 0 0; overflow: hidden; font-family: var(--safe-font-mono); font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
}

@media (max-width: 1060px) {
  .playground-grid { grid-template-columns: 1fr; }
  .result-panel { position: static; }
}

@media (max-width: 620px) {
  .evidence-strip { grid-template-columns: 1fr; }
}
</style>
