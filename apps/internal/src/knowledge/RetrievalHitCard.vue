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
  margin-bottom: 8px;
  padding: 12px;
  border: 1px solid var(--el-border-color);
  border-radius: 4px;
}

.retrieval-hit--above {
  border-left: 4px solid var(--el-color-success);
}

.retrieval-hit--below {
  border-left: 4px solid var(--el-color-info);
  background: var(--el-fill-color-light);
}

.retrieval-hit__meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.retrieval-hit__score {
  font-variant-numeric: tabular-nums;
}

.retrieval-hit__content {
  margin: 0;
  white-space: pre-wrap;
}
</style>
