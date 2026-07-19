<script setup lang="ts">
import type { UploadFile, UploadRawFile } from 'element-plus'
import { ElMessage } from 'element-plus'
import { computed, ref } from 'vue'

import { createSkillScan, type WorkbenchResult } from '@/api/workbench'
import JsonViewer from '@/components/JsonViewer/index.vue'

const MAX_FILE_BYTES = 10 * 1024 * 1024
const isScanning = ref(false)
const selectedFile = ref<UploadRawFile | null>(null)
const result = ref<WorkbenchResult | null>(null)

const selectedFileLabel = computed(() => {
  if (!selectedFile.value) return '尚未选择检测包'
  const size = (selectedFile.value.size / 1024).toFixed(1)
  return `${selectedFile.value.name} · ${size} KB`
})

function handleFileChange(uploadFile: UploadFile): void {
  const raw = uploadFile.raw as UploadRawFile | undefined
  if (!raw) return
  if (raw.size > MAX_FILE_BYTES) {
    selectedFile.value = null
    ElMessage.warning('Skill 检测包不能超过 10 MB')
    return
  }
  selectedFile.value = raw
  result.value = null
}

function handleFileRemove(): void {
  selectedFile.value = null
  result.value = null
}

async function handleScan(): Promise<void> {
  if (!selectedFile.value) {
    ElMessage.warning('请先选择 Skill 文件或 ZIP 检测包')
    return
  }
  isScanning.value = true
  try {
    result.value = await createSkillScan(selectedFile.value)
    ElMessage.success('Skill 静态检测完成，目标代码未执行')
  } finally {
    isScanning.value = false
  }
}
</script>

<template>
  <section class="skill-inspector">
    <article class="skill-inspector__input">
      <div class="skill-inspector__heading">
        <div>
          <h2>Skill 包静态检测</h2>
          <p>支持 ZIP、Python、JavaScript、TypeScript、Markdown、YAML、JSON 与 Shell 文件。</p>
        </div>
        <el-tag type="success" effect="plain">
          不导入、不执行
        </el-tag>
      </div>
      <el-upload
        drag
        action="#"
        :auto-upload="false"
        :limit="1"
        :on-change="handleFileChange"
        :on-remove="handleFileRemove"
        accept=".zip,.py,.js,.ts,.md,.yaml,.yml,.json,.txt,.sh"
      >
        <div class="skill-inspector__drop-title">
          拖入检测包，或点击选择文件
        </div>
        <template #tip>
          <div class="skill-inspector__file-note">
            {{ selectedFileLabel }}；最大 10 MB
          </div>
        </template>
      </el-upload>
      <el-button type="primary" :loading="isScanning" @click="handleScan">
        开始静态检测
      </el-button>
    </article>
    <article v-loading="isScanning" class="skill-inspector__result">
      <div class="skill-inspector__heading">
        <div>
          <h2>行为—权限证据</h2>
          <p>结果包含风险评分、权限偏差、调用图、依赖清单和 Trace。</p>
        </div>
        <el-tag v-if="result?.risk_level" type="warning" effect="light">
          {{ result.risk_level }} / {{ result.risk_score ?? '—' }}
        </el-tag>
      </div>
      <JsonViewer :value="result" empty-text="提交 Skill 后查看静态检测证据。" />
    </article>
  </section>
</template>

<style lang="scss" scoped>
.skill-inspector {
  display: grid;
  grid-template-columns: minmax(300px, 0.72fr) minmax(0, 1.28fr);
  gap: 16px;
  padding-top: 8px;

  &__input,
  &__result {
    padding: 18px;
    border: 1px solid var(--safe-color-border);
    border-radius: var(--safe-radius-card);
    background: var(--safe-color-surface-muted);
  }

  &__input {
    display: grid;
    align-content: start;
    gap: 18px;
  }

  &__heading {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 14px;

    h2 { margin: 0; font-size: 16px; }
    p { margin: 7px 0 0; color: var(--safe-color-text-secondary); font-size: 12px; line-height: 1.6; }
  }

  &__drop-title { color: var(--safe-color-text); font-weight: 700; }
  &__file-note { color: var(--safe-color-text-secondary); font-size: 12px; }
}

@media (max-width: 980px) {
  .skill-inspector { grid-template-columns: 1fr; }
}
</style>
