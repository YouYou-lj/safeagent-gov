<script setup lang="ts">
import type { MetricItem } from '@/types/api'

defineProps<{ items: MetricItem[] }>()
</script>

<template>
  <section class="metric-grid" aria-label="关键指标">
    <article
      v-for="item in items"
      :key="item.label"
      class="metric-grid__item"
      :class="`metric-grid__item--${item.tone ?? 'default'}`"
    >
      <span class="metric-grid__label">{{ item.label }}</span>
      <strong class="metric-grid__value">{{ item.value }}</strong>
      <span v-if="item.detail" class="metric-grid__detail">{{ item.detail }}</span>
    </article>
  </section>
</template>

<style scoped lang="scss">
.metric-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;

  &__item {
    position: relative;
    min-height: 126px;
    padding: 18px;
    overflow: hidden;
    border: 1px solid var(--safe-color-border);
    border-radius: var(--safe-radius-card);
    background: var(--safe-color-surface);

    &::before {
      position: absolute;
      top: 0;
      left: 0;
      width: 4px;
      height: 100%;
      background: var(--safe-color-border-strong);
      content: '';
    }

    &--success::before { background: var(--safe-color-success); }
    &--warning::before { background: var(--safe-color-warning); }
    &--danger::before { background: var(--safe-color-danger); }
  }

  &__label,
  &__detail {
    display: block;
    color: var(--safe-color-text-secondary);
    font-size: 12px;
  }

  &__value {
    display: block;
    margin: 12px 0 7px;
    font-family: var(--safe-font-mono);
    font-size: 28px;
    letter-spacing: -0.04em;
  }
}

@media (max-width: 1100px) {
  .metric-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}

@media (max-width: 560px) {
  .metric-grid { grid-template-columns: 1fr; }
}
</style>
