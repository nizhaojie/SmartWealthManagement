<script setup lang="ts">
// 方案请求的状态列表。客户在这里能看到「请求到哪一步了」，
// 但看不到顾问定稿本身——投顾内容必须经审核后才能送达，本 slice 不做送达面（Q17）。
import { PanelCard } from "@wealth/shared";
import type { AdvisoryRequest } from "../advisory/types";

defineProps<{
  requests: AdvisoryRequest[];
}>();

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
  <PanelCard v-if="requests.length" title="我的方案请求">
    <ul class="requests" data-testid="advisory-requests">
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
        <p class="request__meta">提交时间：{{ request.submitted_at }}</p>
        <p v-if="conditionText(request)" class="request__meta">
          触发条件：{{ conditionText(request) }}
        </p>
      </li>
    </ul>
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
