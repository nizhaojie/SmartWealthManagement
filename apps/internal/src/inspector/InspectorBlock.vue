<script setup lang="ts">
import type { InspectorLoadState } from "./types";

// 检查器里的一块：标题 + 独立的加载 / 失败 / 内容三态。
// 「暂不可用」只出现在本块内部——一栏四块，坏一块不该把另外三块也关掉。
withDefaults(
  defineProps<{
    title: string;
    state: InspectorLoadState;
    /** ready 且内容为空时的文案。 */
    emptyText?: string;
    /** 内容是否为空——由调用方判定，块不认识内容。 */
    empty?: boolean;
  }>(),
  { emptyText: "", empty: false },
);
</script>

<template>
  <section class="inspector-block" data-testid="inspector-block">
    <h3 class="inspector-block__title">{{ title }}</h3>
    <p v-if="state === 'loading'" class="inspector-block__hint">加载中…</p>
    <p
      v-else-if="state === 'failed'"
      class="inspector-block__hint"
      data-testid="inspector-block-unavailable"
    >
      暂不可用
    </p>
    <p v-else-if="empty && emptyText" class="inspector-block__hint">{{ emptyText }}</p>
    <slot v-else />
  </section>
</template>

<style scoped>
.inspector-block {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-2);
}

.inspector-block__title {
  margin: 0;
  color: var(--wm-text-muted);
  font-size: 0.75rem;
  font-weight: 600;
  letter-spacing: 0.06em;
}

.inspector-block__hint {
  margin: 0;
  color: var(--wm-text-muted);
  font-size: 0.8rem;
  line-height: 1.7;
}
</style>
