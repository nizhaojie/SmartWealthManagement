<script setup lang="ts">
/*
 * 列表分页条：总数 + 数字分页，包一层 Element Plus 的 el-pagination。
 *
 * 纯受控：页码、页长、总数都由调用方给（通常来自 `usePagination`），这里只把
 * 「翻到第几页」发出去。控件自己留一份页码就会有两个来源，而两个来源不一致时，
 * 显示出来的页码与列表内容会各说各话。
 *
 * 总数由这里渲染成文字，不走 el-pagination 的 `total` 布局项：它在契约里是和
 * `items` 并列的一等字段（「共 N 条」是这一页之外的事实），写在组件自己的 DOM 上，
 * 两端与测试都看得到同一个数。
 */
withDefaults(
  defineProps<{
    total: number;
    /** 当前页，从 1 起（与后端契约同口径）。 */
    page: number;
    pageSize: number;
    /** 取数在途时置灰：连点两次翻页会打出两个请求，后到的那个覆盖前一个。 */
    disabled?: boolean;
  }>(),
  { disabled: false },
);

const emit = defineEmits<{ "update:page": [page: number] }>();
</script>

<template>
  <div class="pagination-bar" data-testid="pagination-bar">
    <span class="pagination-bar__total" data-testid="pagination-total">共 {{ total }} 条</span>
    <el-pagination
      class="pagination-bar__pager"
      background
      layout="prev, pager, next"
      :current-page="page"
      :page-size="pageSize"
      :total="total"
      :disabled="disabled"
      @current-change="emit('update:page', $event)"
    />
  </div>
</template>

<style scoped>
.pagination-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--wm-space-3);
  margin-top: var(--wm-space-4);
}

.pagination-bar__total {
  color: var(--wm-text-muted);
  font-size: 0.85rem;
  font-variant-numeric: tabular-nums;
}

/* 分页控件贴右：列表的读数在左、操作在右，是这一层统一的排布 */
.pagination-bar__pager {
  margin-left: auto;
}
</style>
