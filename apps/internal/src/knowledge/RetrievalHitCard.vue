<script setup lang="ts">
import type { ChunkHit } from "./types";

// 命中卡片：分数与阈值的相对位置决定它的标签与左侧色条，卡片本身不做判断。
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
  <article class="hit" :class="`hit--${band}`" data-testid="retrieval-hit">
    <header class="hit__head">
      <el-tag :type="tagType" size="small">{{ label }}</el-tag>
      <span class="hit__score">相似度 {{ scoreText }}</span>
      <span class="hit__source">
        {{ hit.source_file }}
        <template v-if="sourceLocation"> · {{ sourceLocation }}</template>
      </span>
    </header>
    <p class="hit__content">{{ hit.content }}</p>
  </article>
</template>

<style scoped>
.hit {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-2);
  padding: var(--wm-space-3);
  /* 3px 左侧强调条由 band 决定（规格定死，不在间距刻度内） */
  border-left: 3px solid var(--wm-border);
  border-radius: var(--wm-radius-sm);
  background-color: var(--wm-bg-subtle);
}

.hit--above {
  border-left-color: var(--wm-color-success);
}

.hit--below {
  border-left-color: var(--wm-color-danger);
}

.hit__head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--wm-space-2);
}

.hit__score {
  color: var(--wm-text-primary);
  font-size: 0.8rem;
  font-variant-numeric: tabular-nums;
}

.hit__source {
  color: var(--wm-text-muted);
  font-size: 0.78rem;
}

.hit__content {
  margin: 0;
  color: var(--wm-text-primary);
  font-size: 0.85rem;
  line-height: 1.75;
  white-space: pre-wrap;
}
</style>
