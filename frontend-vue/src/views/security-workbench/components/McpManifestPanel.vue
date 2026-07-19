<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { reactive, ref } from 'vue'

import {
  createMcpManifestScan,
  type ManifestFormat,
  type WorkbenchResult,
} from '@/api/workbench'
import JsonViewer from '@/components/JsonViewer/index.vue'

const isScanning = ref(false)
const result = ref<WorkbenchResult | null>(null)
const form = reactive({
  sourceName: 'mcp-server.yaml',
  format: 'yaml' as ManifestFormat,
  content: `name: local-files
version: "1.0.0"
simulation_only: true
capabilities: [file_read]
security:
  network_access: false
  write_scope: /data/output
`,
})

async function handleScan(): Promise<void> {
  if (!form.content.trim()) {
    ElMessage.warning('请输入 MCP manifest 或客户端配置')
    return
  }
  isScanning.value = true
  try {
    result.value = await createMcpManifestScan({
      content: form.content,
      format: form.format,
      source_name: form.sourceName,
    })
    ElMessage.success('MCP 描述检测完成，未启动 Server 或连接 endpoint')
  } finally {
    isScanning.value = false
  }
}
</script>

<template>
  <section class="mcp-inspector">
    <article class="mcp-inspector__input">
      <div class="mcp-inspector__heading">
        <div>
          <h2>MCP manifest / client config</h2>
          <p>检测命令启动、内联秘密、私网 endpoint、提示注入和高风险工具能力。</p>
        </div>
        <el-tag type="success" effect="plain">
          纯离线解析
        </el-tag>
      </div>
      <el-form label-position="top">
        <div class="mcp-inspector__form-grid">
          <el-form-item label="来源名称">
            <el-input v-model="form.sourceName" maxlength="160" />
          </el-form-item>
          <el-form-item label="格式">
            <el-select v-model="form.format">
              <el-option label="自动识别" value="auto" />
              <el-option label="YAML" value="yaml" />
              <el-option label="JSON" value="json" />
            </el-select>
          </el-form-item>
        </div>
        <el-form-item label="描述内容">
          <el-input
            v-model="form.content"
            type="textarea"
            :rows="16"
            maxlength="200000"
            show-word-limit
            resize="vertical"
          />
        </el-form-item>
        <el-button type="primary" :loading="isScanning" @click="handleScan">
          检测 MCP 描述
        </el-button>
      </el-form>
    </article>
    <article v-loading="isScanning" class="mcp-inspector__result">
      <div class="mcp-inspector__heading">
        <div>
          <h2>结构与风险证据</h2>
          <p>响应只包含字段路径与风险类别，不回显检测到的秘密值。</p>
        </div>
        <el-tag v-if="result?.risk_level" type="warning" effect="light">
          {{ result.risk_level }} / {{ result.risk_score ?? '—' }}
        </el-tag>
      </div>
      <JsonViewer :value="result" empty-text="提交描述后查看能力清单、风险路径与修复建议。" />
    </article>
  </section>
</template>

<style lang="scss" scoped>
.mcp-inspector {
  display: grid;
  grid-template-columns: minmax(340px, 0.9fr) minmax(0, 1.1fr);
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

  &__form-grid {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 140px;
    gap: 14px;
  }
}

@media (max-width: 980px) {
  .mcp-inspector { grid-template-columns: 1fr; }
}

@media (max-width: 560px) {
  .mcp-inspector__form-grid { grid-template-columns: 1fr; gap: 0; }
}
</style>
