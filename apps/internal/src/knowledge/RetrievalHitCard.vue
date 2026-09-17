<script setup lang="ts">
import type { ChunkHit } from "./types";

defineProps<{
  hit: ChunkHit;
  label: string;
  tagType: "success" | "warning" | "danger" | "info";
  band: "above" | "below";
  sourceLocation: string;
  scoreText: string;
}>();
</script>

<template>
  <article class="retrieval-hit" :class="`retrieval-hit--${band}`">
    <div class="retrieval-hit__meta">
      <el-tag :type="tagType" size="small">{{ label }}</el-tag>
      <span class="retrieval-hit__score">相似度 {{ scoreText }}</span>
      <span>{{ hit.source_file }}<template v-if="sourceLocation"> · {{ sourceLocation }}</template></span>
    </div>
    <p class="retrieval-hit__content">{{ hit.content }}</p>
  </article>
</template>

<style scoped>
.retrieval-hit {
  margin-bottom: var(--wm-space-2);
  padding: var(--wm-space-3);
  /* 命中卡片的 1px 边线（令牌纪律声明的极少数例外） */
  border: 1px solid var(--wm-border);
  border-radius: var(--wm-radius-sm);
}

.retrieval-hit--above {
  border-left: 4px solid var(--wm-color-success);
}

/* 未过线的命中弱化呈现：muted 左条 + 页面底色，不引入新的灰色 */
.retrieval-hit--below {
  border-left: 4px solid var(--wm-text-muted);
  background: var(--wm-bg-page);
}

.retrieval-hit__meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--wm-space-2);
  margin-bottom: var(--wm-space-2);
  color: var(--wm-text-secondary);
  font-size: 13px;
}

.retrieval-hit__score {
  font-variant-numeric: tabular-nums;
}

.retrieval-hit__content {
  margin: 0;
  color: var(--wm-text-primary);
  white-space: pre-wrap;
}
</style>
