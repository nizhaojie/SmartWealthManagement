<script setup lang="ts">
// 方案请求的进度列表，是「我的方案」页的下半区。客户在这里能看到「请求走到哪一步了」，
// 但看不到顾问定稿本身——定稿在上半区的「已放行方案」里，两者是两份不同的东西。
//
// 分页条在这里渲染，页码状态留在页面（`usePagination`，ADR-0024）：空状态要判
// 「一份请求都没有」还是「这一页没有」，那个总数只有页面手里有。取数与翻页同理，
// 这一段因此是受控的——它只把「翻到第几页」发出去。
import { PaginationBar, PanelCard } from "@wealth/shared";
import { formatDateTime } from "./timeliness";
import type { AdvisoryRequest } from "./types";

defineProps<{
  requests: AdvisoryRequest[];
  /** 过滤后的请求总数，由服务端给。 */
  total: number;
  page: number;
  pageSize: number;
  loading: boolean;
}>();

const emit = defineEmits<{ "update:page": [page: number] }>();

const STATUS_HINTS: Record<string, string> = {
  待处理: "顾问尚未开始处理",
  处理中: "顾问正在处理",
  已完成: "顾问已出具方案",
  已关闭: "该请求已关闭",
};

const FILTER_LABELS: Record<string, string> = {
  product_type: "产品类型",
  risk_level: "产品风险等级",
  min_amount: "起投金额（上限）",
  min_expected_return: "业绩基准（下限）",
  max_term_days: "期限（天，上限）",
};

function conditionText(request: AdvisoryRequest): string {
  return Object.entries(request.filters)
    .map(([key, value]) => `${FILTER_LABELS[key] ?? key}：${value}`)
    .join("；");
}

function statusHint(status: string): string {
  return STATUS_HINTS[status] ?? "";
}
</script>

<template>
  <!-- `total > 0` 时即使本页是空的也留着这一块：撤掉它，翻过头的人就困在那一页上。 -->
  <PanelCard v-if="requests.length || total > 0" title="方案请求进度">
    <ul v-if="requests.length" class="requests" data-testid="advisory-requests">
      <li
        v-for="request in requests"
        :key="request.request_no"
        class="request"
        data-testid="advisory-request"
      >
        <p class="request__head">
          <strong class="request__status" data-testid="advisory-status">{{ request.status }}</strong>
          <span class="request__hint">{{ statusHint(request.status) }}</span>
        </p>
        <p class="request__meta">请求编号：{{ request.request_no }}</p>
        <p class="request__meta">提交时间：{{ formatDateTime(request.submitted_at) }}</p>
        <p v-if="conditionText(request)" class="request__meta">
          触发条件：{{ conditionText(request) }}
        </p>
      </li>
    </ul>

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
.requests {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-4);
  margin: 0;
  padding: 0;
  list-style: none;
}

.request {
  padding: var(--wm-space-3) var(--wm-space-4);
  /* 请求卡的 1px 描边（令牌纪律声明的极少数例外） */
  border: 1px solid var(--wm-border-hairline);
  border-radius: var(--wm-radius-md);
  background-color: var(--wm-bg-subtle);
}

.request__head {
  display: flex;
  align-items: baseline;
  gap: var(--wm-space-2);
  margin: 0 0 var(--wm-space-1);
}

.request__status {
  color: var(--wm-text-primary);
  font-size: 0.95rem;
  font-weight: 600;
}

.request__hint,
.request__meta {
  color: var(--wm-text-muted);
  font-size: 0.85rem;
}

.request__meta {
  margin: 0;
  line-height: 1.7;
}
</style>
