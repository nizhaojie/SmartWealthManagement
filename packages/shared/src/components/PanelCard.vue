<script setup lang="ts">
// 02 的卡片容器：白面 + 发丝线 + 圆角 + 卡片阴影，顶部一条发丝渐变线。
// 不知道卡片里装的是什么，也不认识任何业务字段。
import { useSlots } from "vue";

defineProps<{
  title: string;
}>();

const slots = useSlots();
</script>

<template>
  <section class="panel-card" data-testid="panel-card">
    <header class="panel-card__header">
      <h3 class="panel-card__title">{{ title }}</h3>
      <div v-if="slots.actions" class="panel-card__actions">
        <slot name="actions" />
      </div>
    </header>
    <div class="panel-card__body">
      <slot />
    </div>
  </section>
</template>

<style scoped>
.panel-card {
  position: relative;
  border: 1px solid var(--wm-border);
  border-radius: var(--wm-radius-md);
  background-color: var(--wm-bg-card);
  box-shadow: var(--wm-shadow-card);
}

/* 02 的面板发丝渐变线（.panel::after） */
.panel-card::after {
  content: "";
  position: absolute;
  top: 0;
  left: var(--wm-space-4);
  right: var(--wm-space-4);
  height: 1px;
  pointer-events: none;
  background: linear-gradient(90deg, transparent, var(--wm-color-primary), transparent);
  opacity: 0.26;
}

.panel-card__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--wm-space-3);
  padding: var(--wm-space-3) var(--wm-space-5);
  /* 分隔标题栏与内容的细线（令牌纪律声明的极少数 1px 例外） */
  border-bottom: 1px solid var(--wm-border-hairline);
}

.panel-card__title {
  margin: 0;
  color: var(--wm-text-primary);
  font-size: 1rem;
  font-weight: 600;
}

.panel-card__actions {
  display: flex;
  align-items: center;
  gap: var(--wm-space-2);
  min-width: 0;
}

.panel-card__body {
  padding: var(--wm-space-5);
}

@media (prefers-reduced-motion: no-preference) {
  .panel-card {
    animation: wbRise 0.55s var(--wm-ease-rise) backwards;
  }

  .panel-card::after {
    animation: wbGlow 5s ease-in-out infinite;
  }
}
</style>
