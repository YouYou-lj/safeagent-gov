<script setup lang="ts">
import { Refresh } from '@element-plus/icons-vue'

withDefaults(
  defineProps<{
    title: string
    description: string
    loading?: boolean
    refreshable?: boolean
  }>(),
  { loading: false, refreshable: false },
)

defineEmits<{ refresh: [] }>()
</script>

<template>
  <header class="page-header">
    <div>
      <p class="page-header__eyebrow">
        GOVSAFEAGENT / CONTROL PLANE
      </p>
      <h1 class="page-header__title">
        {{ title }}
      </h1>
      <p class="page-header__description">
        {{ description }}
      </p>
    </div>
    <div class="page-header__actions">
      <slot name="actions" />
      <el-button
        v-if="refreshable"
        :icon="Refresh"
        :loading="loading"
        @click="$emit('refresh')"
      >
        刷新证据
      </el-button>
    </div>
  </header>
</template>

<style scoped lang="scss">
.page-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 24px;

  &__eyebrow {
    margin: 0 0 8px;
    color: var(--safe-color-accent);
    font-size: 11px;
    font-weight: 800;
    letter-spacing: 0.12em;
  }

  &__title {
    margin: 0;
    font-size: clamp(26px, 3vw, 36px);
    letter-spacing: -0.04em;
  }

  &__description {
    margin: 8px 0 0;
    color: var(--safe-color-text-secondary);
  }

  &__actions {
    display: flex;
    flex-wrap: wrap;
    justify-content: flex-end;
    gap: 10px;
  }
}

@media (max-width: 767px) {
  .page-header {
    align-items: flex-start;
    flex-direction: column;

    &__actions {
      justify-content: flex-start;
      width: 100%;
    }
  }
}
</style>
