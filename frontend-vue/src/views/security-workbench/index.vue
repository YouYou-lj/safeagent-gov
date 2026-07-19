<script setup lang="ts">
import { ref } from 'vue'

import PageHeader from '@/components/PageHeader/index.vue'
import AgentInspectionPanel from '@/views/security-workbench/components/AgentInspectionPanel.vue'
import McpManifestPanel from '@/views/security-workbench/components/McpManifestPanel.vue'
import ModelSessionPanel from '@/views/security-workbench/components/ModelSessionPanel.vue'
import SkillInspectionPanel from '@/views/security-workbench/components/SkillInspectionPanel.vue'

const activePanel = ref('skill')
</script>

<template>
  <div class="security-workbench">
    <PageHeader
      title="安全检测工作台"
      description="在同一入口静态检测 Skill 与 MCP 描述、验证 Agent 路由，并以一次性凭据测试主流模型通信。"
    />
    <el-alert
      class="security-workbench__boundary"
      type="info"
      :closable="false"
      show-icon
      title="检测目标始终视为不可信输入；MCP 描述不会启动，临时模型凭据不会写入 Store、localStorage 或审计正文。"
    />
    <el-tabs v-model="activePanel" class="security-workbench__tabs">
      <el-tab-pane label="Skill 检测" name="skill">
        <SkillInspectionPanel />
      </el-tab-pane>
      <el-tab-pane label="MCP 描述检测" name="mcp">
        <McpManifestPanel />
      </el-tab-pane>
      <el-tab-pane label="Agent 路由测试" name="agent">
        <AgentInspectionPanel />
      </el-tab-pane>
      <el-tab-pane label="模型临时通信" name="model">
        <ModelSessionPanel />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<style lang="scss" scoped>
.security-workbench {
  display: grid;
  gap: 20px;

  &__boundary {
    border: 1px solid var(--safe-color-border);
  }

  &__tabs {
    padding: 6px 20px 20px;
    border: 1px solid var(--safe-color-border);
    border-radius: var(--safe-radius-card);
    background: var(--safe-color-surface);
    box-shadow: var(--safe-shadow-surface);
  }
}

@media (max-width: 767px) {
  .security-workbench__tabs {
    padding-right: 14px;
    padding-left: 14px;
  }
}
</style>
