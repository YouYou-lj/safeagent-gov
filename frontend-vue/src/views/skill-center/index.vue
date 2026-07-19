<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { getSkillMetrics, getSkillRegistry } from '@/api/governance'
import JsonViewer from '@/components/JsonViewer/index.vue'
import MetricGrid from '@/components/MetricGrid/index.vue'
import PageHeader from '@/components/PageHeader/index.vue'
import type { JsonObject, MetricItem, SkillRegistrySnapshot } from '@/types/api'
import { readNumber } from '@/utils/data'

const loading = ref(false)
const registry = ref<SkillRegistrySnapshot | null>(null)
const runtimeMetrics = ref<JsonObject | null>(null)
const selectedSkill = ref<JsonObject | null>(null)

const metrics = computed<MetricItem[]>(() => [
  { label: '注册 Skill', value: registry.value?.skill_count ?? '—', detail: '独立目录与签名清单', tone: 'success' },
  { label: '强制 Skill', value: registry.value?.mandatory_count ?? '—', detail: '失败即阻断', tone: 'warning' },
  { label: '实际调用', value: readNumber(runtimeMetrics.value, 'actual_calls') || '—', detail: '运行期审计计数' },
  {
    label: '失败调用',
    value: readNumber(runtimeMetrics.value, 'failed_calls'),
    detail: '错误不会静默降级',
    tone: readNumber(runtimeMetrics.value, 'failed_calls') ? 'danger' : 'success',
  },
])

async function loadSkills(): Promise<void> {
  loading.value = true
  try {
    const [snapshot, metricsSnapshot] = await Promise.all([getSkillRegistry(), getSkillMetrics()])
    registry.value = snapshot
    runtimeMetrics.value = metricsSnapshot
  } finally {
    loading.value = false
  }
}

onMounted(() => void loadSkills())
</script>

<template>
  <div class="safe-page">
    <PageHeader
      title="Skill 中心"
      description="主办方可直接核验创新 Skill 的注册清单、执行模式、触发阶段与内容哈希。"
      refreshable
      :loading="loading"
      @refresh="loadSkills"
    />
    <MetricGrid :items="metrics" />
    <section class="safe-grid--two skill-layout">
      <article class="safe-panel">
        <h2 class="safe-panel__title">
          可信注册表
        </h2>
        <p class="safe-panel__subtitle">
          仅加载仓库独立 skills/ 目录中通过严格契约校验的能力。
        </p>
        <el-table v-loading="loading" :data="registry?.skills ?? []" empty-text="暂无 Skill">
          <el-table-column label="名称 / 版本" min-width="180">
            <template #default="scope">
              <button class="skill-link" type="button" @click="selectedSkill = scope.row">
                <strong>{{ scope.row.definition.name }}</strong>
                <small>{{ scope.row.definition.version }}</small>
              </button>
            </template>
          </el-table-column>
          <el-table-column label="模式" width="110">
            <template #default="scope">
              {{ scope.row.definition.execution_mode }}
            </template>
          </el-table-column>
          <el-table-column label="失败策略" width="110">
            <template #default="scope">
              {{ scope.row.definition.failure_policy }}
            </template>
          </el-table-column>
          <el-table-column label="哈希" min-width="130">
            <template #default="scope">
              <span class="safe-mono digest">{{ scope.row.content_hash }}</span>
            </template>
          </el-table-column>
        </el-table>
      </article>
      <article class="safe-panel">
        <h2 class="safe-panel__title">
          Skill 证据详情
        </h2>
        <p class="safe-panel__subtitle">
          选择注册项查看完整声明；页面不支持动态上传或执行未受信代码。
        </p>
        <JsonViewer :value="selectedSkill" empty-text="从左侧选择一个 Skill 查看清单与内容哈希。" />
      </article>
    </section>
  </div>
</template>

<style scoped lang="scss">
.skill-layout { grid-template-columns: minmax(0, 1.2fr) minmax(300px, 0.8fr); }

.skill-link {
  display: grid;
  padding: 0;
  border: 0;
  color: var(--safe-color-accent);
  background: transparent;
  text-align: left;
  cursor: pointer;

  small { margin-top: 3px; color: var(--safe-color-text-secondary); font-family: var(--safe-font-mono); }
}

.digest {
  display: block;
  overflow: hidden;
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

@media (max-width: 1050px) {
  .skill-layout { grid-template-columns: 1fr; }
}
</style>
