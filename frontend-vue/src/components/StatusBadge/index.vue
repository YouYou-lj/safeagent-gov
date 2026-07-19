<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ status: string }>()

const type = computed(() => {
  const normalized = props.status.toLowerCase()
  if (['ok', 'healthy', 'success', 'succeeded', 'completed', 'enabled', 'allow'].includes(normalized)) return 'success'
  if (['failed', 'blocked', 'denied', 'danger', 'unhealthy'].includes(normalized)) return 'danger'
  if (['pending', 'queued', 'running', 'warning', 'require_approval'].includes(normalized)) return 'warning'
  return 'info'
})
</script>

<template>
  <el-tag :type="type" effect="light" round>
    {{ status }}
  </el-tag>
</template>
