<script setup lang="ts">
import { PanelCard } from "@wealth/shared";
import { formatDateTime } from "../format";
import type { AnalyticsHistoryItem } from "./types";

/**
 * 右侧栏里的历史查询：只列条目、只上抛选中项。
 *
 * 数据由工作区拉好传进来——检查器组件不自己取数，否则「问完一轮刷新历史」
 * 就要在这里再挂一条跨组件通道。留痕行里没有结果集，所以栏里也不放结果。
 */
defineProps<{
  history: AnalyticsHistoryItem[];
  selectedId: number | null;
  failed: boolean;
}>();

const emit = defineEmits<{ select: [id: number] }>();
</script>

<template>
  <PanelCard title="历史查询">
    <p v-if="!history.length && failed" class="rail__hint" role="alert" data-testid="history-error">
      历史查询加载失败，刷新页面重试。
    </p>
    <ul v-else-if="history.length" class="history">
      <li v-for="entry in history" :key="entry.id">
        <button
          type="button"
          class="history__item"
          :class="{ 'history__item--active': entry.id === selectedId }"
          :aria-current="entry.id === selectedId ? 'true' : undefined"
          :data-testid="`history-item-${entry.id}`"
          @click="emit('select', entry.id)"
        >
          <strong class="history__question">{{ entry.question }}</strong>
          <span class="history__meta">
            {{ entry.status }} · {{ formatDateTime(entry.create_time) }}
          </span>
        </button>
      </li>
    </ul>
    <p v-else class="rail__hint" data-testid="history-empty">还没有历史查询</p>
  </PanelCard>
</template>

<style scoped>
.history {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-1);
  margin: 0;
  padding: 0;
  list-style: none;
  max-height: calc(var(--wm-space-6) * 14);
  overflow-y: auto;
}

.history__item {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-1);
  width: 100%;
  padding: var(--wm-space-2) var(--wm-space-3);
  /* 细边框属令牌纪律声明的极少数 1px 例外；常态透明，只为激活态不让内容位移 */
  border: 1px solid transparent;
  border-radius: var(--wm-radius-sm);
  background-color: transparent;
  font-family: inherit;
  text-align: left;
  cursor: pointer;
}

.history__item:hover {
  background-color: var(--wm-bg-page);
}

/* 激活项是淡染底：底上的文字走 primary-strong（与客户列表同一手法） */
.history__item--active {
  border-color: var(--wm-color-primary-tint);
  background-color: var(--wm-color-primary-tint);
}

.history__item--active .history__question {
  color: var(--wm-color-primary-strong);
}

.history__question {
  color: var(--wm-text-primary);
  font-size: 0.82rem;
  font-weight: 500;
  line-height: 1.6;
}

.history__meta {
  color: var(--wm-text-muted);
  font-size: 0.75rem;
}

.rail__hint {
  margin: 0;
  color: var(--wm-text-muted);
  font-size: 0.85rem;
  line-height: 1.7;
}
</style>
