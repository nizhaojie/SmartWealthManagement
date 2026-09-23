<script setup lang="ts">
import { PaginationBar, PanelCard } from "@wealth/shared";
import { formatDateTime } from "../format";
import type { AnalyticsHistoryItem } from "./types";

/**
 * 右侧栏里的历史查询：只列条目、只上抛选中项与翻页。
 *
 * 数据由工作区拉好传进来——检查器组件不自己取数，否则「问完一轮刷新历史」
 * 就要在这里再挂一条跨组件通道。留痕行里没有结果集，所以栏里也不放结果。
 *
 * 分页（ADR-0024）同理：页码与总数也由工作区持有，这里只把「翻到第几页」发出去。
 * 栏里留一份页码就会有两个来源，而两个来源不一致时，显示的页码与列表内容各说各话。
 */
defineProps<{
  history: AnalyticsHistoryItem[];
  selectedId: number | null;
  failed: boolean;
  total: number;
  /** 当前页，从 1 起（与后端契约同口径）。 */
  page: number;
  pageSize: number;
  loading: boolean;
}>();

const emit = defineEmits<{ select: [id: number]; "update:page": [page: number] }>();
</script>

<template>
  <PanelCard title="历史查询">
    <p v-if="failed" class="rail__hint" role="alert" data-testid="history-error">
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
    <p v-else-if="total === 0" class="rail__hint" data-testid="history-empty">还没有历史查询</p>
    <!-- 有留痕但这一页恰好是空的（页码跑到了末页之后）：那不是「你还没问过」 -->
    <p v-else class="rail__hint" data-testid="history-page-empty">
      这一页没有历史查询，翻回前面几页看看。
    </p>

    <!-- 取不到时 `total` 归零，分页条与列表同进同退；越界页 `total` 不变，所以它仍然留着 -->
    <PaginationBar
      v-if="total > 0"
      :total="total"
      :page="page"
      :page-size="pageSize"
      :disabled="loading"
      @update:page="emit('update:page', $event)"
    />
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
