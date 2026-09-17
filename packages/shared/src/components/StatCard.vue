<script setup lang="ts">
import { computed } from "vue";
import type { StatCardAccent, StatCardTrend } from "./statCard";

const props = withDefaults(
  defineProps<{
    title: string;
    value: string | number;
    trend?: StatCardTrend;
    accent?: StatCardAccent;
  }>(),
  {
    accent: "primary",
  },
);

const accentClass = computed(() => `stat-card--accent-${props.accent}`);
</script>

<template>
  <div class="stat-card" :class="accentClass" data-testid="stat-card">
    <div v-if="$slots.icon" class="stat-card__icon" aria-hidden="true">
      <slot name="icon" />
    </div>
    <div class="stat-card__body">
      <p class="stat-card__title">{{ title }}</p>
      <p class="stat-card__value">{{ value }}</p>
      <p
        v-if="trend"
        class="stat-card__trend"
        :class="`stat-card__trend--${trend.direction}`"
        data-testid="stat-card-trend"
      >
        <span aria-hidden="true">{{ trend.direction === "up" ? "↑" : "↓" }}</span>
        {{ trend.label }}
      </p>
    </div>
  </div>
</template>

<style scoped>
.stat-card {
  display: flex;
  align-items: flex-start;
  gap: var(--wm-space-3);
  padding: var(--wm-space-4) var(--wm-space-5);
  border: 1px solid var(--wm-border);
  /* 规格定死的 3px 左边条（ticket 03），不在间距刻度内；颜色经下方 accent 枚举映射 */
  border-left: 3px solid var(--stat-card-accent);
  border-radius: var(--wm-radius-lg);
  background-color: var(--wm-bg-card);
  box-shadow: var(--wm-shadow-card);
}

.stat-card__body {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-1);
  min-width: 0;
}

.stat-card__title {
  margin: 0;
  color: var(--wm-text-muted);
  font-size: 0.85rem;
}

.stat-card__value {
  margin: 0;
  color: var(--wm-text-primary);
  font-size: 1.5rem;
  font-weight: 700;
  line-height: 1.2;
}

.stat-card__trend {
  display: flex;
  align-items: center;
  gap: var(--wm-space-1);
  margin: 0;
  font-size: 0.85rem;
}

/* 涨跌着色只有一个实现点：方向在这里翻成令牌色，调用方不传颜色 */
.stat-card__trend--up {
  color: var(--wm-color-up);
}

.stat-card__trend--down {
  color: var(--wm-color-down);
}

.stat-card__icon {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  width: var(--wm-space-6);
  height: var(--wm-space-6);
  border-radius: var(--wm-radius-md);
  color: var(--stat-card-accent);
  font-size: var(--wm-space-4);
  background: color-mix(in srgb, var(--stat-card-accent) 10%, white);
}

/* accent 枚举的完整映射：六个语义名之外没有任何着色入口 */
.stat-card--accent-primary {
  --stat-card-accent: var(--wm-color-primary);
}

.stat-card--accent-up {
  --stat-card-accent: var(--wm-color-up);
}

.stat-card--accent-down {
  --stat-card-accent: var(--wm-color-down);
}

.stat-card--accent-success {
  --stat-card-accent: var(--wm-color-success);
}

.stat-card--accent-warning {
  --stat-card-accent: var(--wm-color-warning);
}

.stat-card--accent-danger {
  --stat-card-accent: var(--wm-color-danger);
}
</style>
