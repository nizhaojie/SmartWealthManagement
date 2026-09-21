<script setup lang="ts">
import { PanelCard } from "@wealth/shared";
import { formatDateTime, formatMoney } from "../format";
import type { OperationAdvice } from "./types";

/**
 * 操作建议的载荷，审核页与详情页共用。
 *
 * 这里只有建议本体的四件事——**一个产品、一个方向、一个金额、一条理由**：候选池、
 * 配置建议与画像警示是配置方案特有的（ADR-0020），把方案的渲染件拿过来复用，
 * 会在建议上渲染出一堆空字段，而那种页面看起来仍然是「正常」的。
 */
defineProps<{ advice: OperationAdvice }>();
</script>

<template>
  <PanelCard title="操作建议" data-testid="advice-payload">
    <p class="payload__line" data-testid="advice-product">
      {{ advice.product_name ?? advice.product_code }}（{{ advice.product_code }}）
    </p>
    <div class="payload__meta">
      <span data-testid="advice-direction">{{ advice.direction }}</span>
      <span class="payload__amount" data-testid="advice-amount">
        {{ formatMoney(advice.amount) }}
      </span>
      <span class="payload__time" data-testid="advice-generated-at">
        {{ formatDateTime(advice.generated_at) }}
      </span>
    </div>
    <p class="payload__reason" data-testid="advice-reason">{{ advice.reason }}</p>
    <p class="payload__disclaimer" data-testid="advice-disclaimer">{{ advice.disclaimer }}</p>
  </PanelCard>
</template>

<style scoped>
.payload__line {
  margin: 0;
  color: var(--wm-text-primary);
  font-size: 0.95rem;
  font-weight: 600;
}

.payload__meta {
  display: flex;
  flex-wrap: wrap;
  gap: var(--wm-space-3);
  margin-top: var(--wm-space-2);
  color: var(--wm-text-muted);
  font-size: 0.85rem;
  font-variant-numeric: tabular-nums;
}

.payload__reason {
  margin: var(--wm-space-3) 0 0;
  color: var(--wm-text-primary);
  font-size: 0.85rem;
  line-height: 1.75;
}

.payload__disclaimer {
  margin: var(--wm-space-3) 0 0;
  color: var(--wm-text-muted);
  font-size: 0.78rem;
  line-height: 1.7;
}
</style>
