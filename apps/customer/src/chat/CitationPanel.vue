<script setup lang="ts">
// 引用面板：文档标识 + 来源文件 + 段落位置。点击角标后展开，再点收起。
import type { Citation } from "./api";

defineProps<{
  citation: Citation;
  panelId: string;
}>();
</script>

<template>
  <div
    :id="panelId"
    class="citation-panel"
    role="dialog"
    :aria-label="`引用来源：${citation.title}`"
    data-testid="citation-panel"
  >
    <p class="citation-panel__title">{{ citation.title }}</p>
    <p class="citation-panel__meta">来源文件：{{ citation.source_file }}</p>
    <p v-if="citation.heading_path.length" class="citation-panel__meta">
      段落位置：{{ citation.heading_path.join(" / ") }}
    </p>
  </div>
</template>

<style scoped>
.citation-panel {
  margin-top: var(--wm-space-2);
  padding: var(--wm-space-2) var(--wm-space-3);
  /* 引用面板的 1px 边线（令牌纪律声明的极少数例外） */
  border: 1px solid var(--wm-border-hairline);
  border-radius: var(--wm-radius-sm);
  background-color: var(--wm-bg-page);
  font-size: 0.85rem;
}

.citation-panel p {
  margin: 0;
}

.citation-panel__title {
  color: var(--wm-text-primary);
  font-weight: 600;
}

.citation-panel__meta {
  color: var(--wm-text-muted);
}
</style>
