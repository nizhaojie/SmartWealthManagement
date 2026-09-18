<script setup lang="ts">
// 02 的 .meter / .track：标签 + 百分比 + 5px 胶囊条。
// 标签、百分比、颜色全部经 props 传入——它不知道这个百分比意味着什么。
import { computed } from "vue";
import type { Accent } from "./accent";

const props = withDefaults(
  defineProps<{
    label: string;
    /** 0–100 的百分比；越界值在组件内夹紧，调用方不必先做边界处理。 */
    percent: number;
    accent?: Accent;
  }>(),
  {
    accent: "primary",
  },
);

const clampedPercent = computed(() => Math.min(100, Math.max(0, props.percent)));
const accentClass = computed(() => `meter-bar--accent-${props.accent}`);
</script>

<template>
  <div class="meter-bar" :class="accentClass" data-testid="meter-bar">
    <div class="meter-bar__head">
      <span class="meter-bar__label">{{ label }}</span>
      <b class="meter-bar__value">{{ clampedPercent }}%</b>
    </div>
    <div
      class="meter-bar__track"
      role="progressbar"
      :aria-label="label"
      aria-valuemin="0"
      aria-valuemax="100"
      :aria-valuenow="clampedPercent"
    >
      <span class="meter-bar__fill" :style="{ width: `${clampedPercent}%` }"></span>
    </div>
  </div>
</template>

<style scoped>
.meter-bar {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-1);
}

.meter-bar__head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--wm-space-2);
  font-size: 0.8rem;
  color: var(--wm-text-muted);
}

.meter-bar__value {
  color: var(--wm-text-primary);
  font-variant-numeric: tabular-nums;
}

.meter-bar__track {
  /* 规格定死的 5px 轨道，不在间距刻度内（02 的 .track） */
  height: 5px;
  border-radius: var(--wm-radius-pill);
  background-color: var(--wm-border-hairline);
  overflow: hidden;
}

.meter-bar__fill {
  display: block;
  height: 100%;
  border-radius: var(--wm-radius-pill);
  background-color: var(--meter-bar-accent);
}

/* accent 枚举的完整映射：六个语义名之外没有任何着色入口 */
.meter-bar--accent-primary {
  --meter-bar-accent: var(--wm-color-primary);
}

.meter-bar--accent-up {
  --meter-bar-accent: var(--wm-color-up);
}

.meter-bar--accent-down {
  --meter-bar-accent: var(--wm-color-down);
}

.meter-bar--accent-success {
  --meter-bar-accent: var(--wm-color-success);
}

.meter-bar--accent-warning {
  --meter-bar-accent: var(--wm-color-warning);
}

.meter-bar--accent-danger {
  --meter-bar-accent: var(--wm-color-danger);
}
</style>
