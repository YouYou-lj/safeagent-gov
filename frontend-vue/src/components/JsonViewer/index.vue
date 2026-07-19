<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{ value: unknown; emptyText?: string }>(), {
  emptyText: '暂无可展示证据',
})

const content = computed(() => (props.value === null || props.value === undefined ? '' : JSON.stringify(props.value, null, 2)))
</script>

<template>
  <pre v-if="content" class="json-viewer">{{ content }}</pre>
  <div v-else class="safe-empty">
    {{ emptyText }}
  </div>
</template>

<style scoped lang="scss">
.json-viewer {
  max-height: 520px;
  margin: 0;
  padding: 16px;
  overflow: auto;
  border: 1px solid var(--safe-color-border);
  border-radius: var(--safe-radius-control);
  color: var(--safe-color-code-text);
  background: var(--safe-color-code-background);
  font-family: var(--safe-font-mono);
  font-size: 12px;
  line-height: 1.65;
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
