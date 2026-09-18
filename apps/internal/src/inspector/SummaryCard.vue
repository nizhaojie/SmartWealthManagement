<script setup lang="ts">
import { PanelCard } from "@wealth/shared";
import type { SummaryRow } from "./types";

// 模块级检查器：把自己「筛了什么、剩几条」摆出来。行内容由页面给——
// 卡片不认识预警，也不认识工单。
defineProps<{
  title: string;
  rows: SummaryRow[];
  note?: string;
}>();
</script>

<template>
  <PanelCard :title="title">
    <dl class="summary">
      <div v-for="row in rows" :key="row.label" class="summary__row">
        <dt>{{ row.label }}</dt>
        <dd :data-testid="row.testId">{{ row.value }}</dd>
      </div>
    </dl>
    <p v-if="note" class="summary__note">{{ note }}</p>
  </PanelCard>
</template>

<style scoped>
.summary {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-2);
  margin: 0;
}

.summary__row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--wm-space-2);
}

.summary__row dt {
  color: var(--wm-text-muted);
  font-size: 0.8rem;
  white-space: nowrap;
}

.summary__row dd {
  margin: 0;
  color: var(--wm-text-primary);
  font-size: 0.82rem;
  text-align: right;
  font-variant-numeric: tabular-nums;
}

.summary__note {
  margin: var(--wm-space-3) 0 0;
  color: var(--wm-text-muted);
  font-size: 0.78rem;
  line-height: 1.7;
}
</style>
