<script setup lang="ts">
import { useSlots } from "vue";

defineProps<{
  title: string;
}>();

const slots = useSlots();
</script>

<template>
  <section class="section-card" data-testid="section-card">
    <header class="section-card__header">
      <h3 class="section-card__title">{{ title }}</h3>
      <div v-if="slots.actions" class="section-card__actions">
        <slot name="actions" />
      </div>
    </header>
    <div class="section-card__body">
      <slot />
    </div>
  </section>
</template>

<style scoped>
.section-card {
  border: 1px solid var(--wm-border);
  border-radius: var(--wm-radius-lg);
  background-color: var(--wm-bg-card);
  box-shadow: var(--wm-shadow-card);
}

.section-card__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--wm-space-3);
  padding: var(--wm-space-3) var(--wm-space-5);
  /* 分隔标题栏与内容的细线（令牌纪律声明的极少数 1px 例外） */
  border-bottom: 1px solid var(--wm-border-hairline);
}

.section-card__title {
  margin: 0;
  color: var(--wm-text-primary);
  font-size: 1rem;
  font-weight: 600;
}

.section-card__actions {
  display: flex;
  align-items: center;
  gap: var(--wm-space-2);
  min-width: 0;
}

.section-card__body {
  padding: var(--wm-space-5);
}
</style>
