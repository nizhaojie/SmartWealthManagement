<script setup lang="ts">
import { PanelCard } from "@wealth/shared";
import { formatDateTime } from "../format";
import type { AnalyticsHistoryItem } from "./types";

/**
 * 一条留痕记录的详情。
 *
 * 画什么由留痕表决定：它只有问题、生成的查询、状态、行数、截断与错误码，
 * 没有结果集与解读——所以这里不画表格，也不补一个看起来像结果的空表格。
 * 要看当前数据，就是重新提问。
 */
const props = defineProps<{ record: AnalyticsHistoryItem }>();
</script>

<template>
  <PanelCard title="历史记录">
    <div class="detail" data-testid="history-detail">
      <dl class="facts">
        <div class="facts__row">
          <dt>问题</dt>
          <dd data-testid="history-detail-question">{{ props.record.question }}</dd>
        </div>
        <div class="facts__row">
          <dt>状态</dt>
          <dd data-testid="history-detail-status">{{ props.record.status }}</dd>
        </div>
        <div class="facts__row">
          <dt>返回行数</dt>
          <dd>{{ props.record.row_count === null ? "—" : `${props.record.row_count} 行` }}</dd>
        </div>
        <div class="facts__row">
          <dt>是否截断</dt>
          <dd>{{ props.record.truncated ? "是" : "否" }}</dd>
        </div>
        <div class="facts__row">
          <dt>错误码</dt>
          <dd>{{ props.record.error_code === null ? "—" : props.record.error_code }}</dd>
        </div>
        <div class="facts__row">
          <dt>提问时间</dt>
          <dd>{{ formatDateTime(props.record.create_time) }}</dd>
        </div>
      </dl>

      <p class="detail__label">生成的查询</p>
      <pre class="detail__sql" data-testid="history-detail-sql">{{ props.record.sql ?? "—" }}</pre>

      <p class="detail__note">
        留痕只保存问题、生成的查询与状态，不保存结果集；要看当前数据请重新提问。
      </p>
    </div>
  </PanelCard>
</template>

<style scoped>
.facts {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-2);
  margin: 0;
}

.facts__row {
  display: flex;
  align-items: baseline;
  gap: var(--wm-space-3);
}

.facts__row dt {
  flex-shrink: 0;
  width: calc(var(--wm-space-6) * 2);
  color: var(--wm-text-muted);
  font-size: 0.8rem;
}

.facts__row dd {
  margin: 0;
  color: var(--wm-text-primary);
  font-size: 0.85rem;
  font-variant-numeric: tabular-nums;
}

.detail__label {
  margin: var(--wm-space-4) 0 var(--wm-space-2);
  color: var(--wm-text-muted);
  font-size: 0.8rem;
}

.detail__sql {
  margin: 0;
  padding: var(--wm-space-3);
  border-radius: var(--wm-radius-sm);
  background-color: var(--wm-bg-subtle);
  color: var(--wm-text-primary);
  font-family: var(--wm-font-mono);
  font-size: 0.78rem;
  line-height: 1.7;
  overflow-x: auto;
  white-space: pre-wrap;
}

/* 装饰性说明走豁免档（--wm-text-placeholder 仅限 placeholder 与装饰） */
.detail__note {
  margin: var(--wm-space-3) 0 0;
  color: var(--wm-text-placeholder);
  font-size: 0.78rem;
  line-height: 1.7;
}
</style>
