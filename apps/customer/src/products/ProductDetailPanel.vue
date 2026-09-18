<script setup lang="ts">
// 产品详情：只列已披露的产品要素，不加任何评价性的字段。
import { PanelCard } from "@wealth/shared";
import type { Product } from "./types";

defineProps<{
  product: Product;
  error: string;
}>();
</script>

<template>
  <PanelCard title="产品详情">
    <p v-if="error" class="detail__error" role="alert">{{ error }}</p>
    <dl class="detail" data-testid="product-detail">
      <div class="detail__row"><dt>代码</dt><dd>{{ product.product_code }}</dd></div>
      <div class="detail__row"><dt>名称</dt><dd>{{ product.product_name }}</dd></div>
      <div class="detail__row"><dt>类型</dt><dd>{{ product.product_type }}</dd></div>
      <div class="detail__row"><dt>产品风险等级</dt><dd>{{ product.risk_level }}</dd></div>
      <div class="detail__row"><dt>业绩基准</dt><dd>{{ product.expected_return }}</dd></div>
      <div class="detail__row"><dt>期限（天）</dt><dd>{{ product.term_days }}</dd></div>
      <div class="detail__row"><dt>起投金额（元）</dt><dd>{{ product.min_amount }}</dd></div>
      <div class="detail__row"><dt>费率（%）</dt><dd>{{ product.fee_rate }}</dd></div>
      <div class="detail__row"><dt>基金经理</dt><dd>{{ product.fund_manager ?? "—" }}</dd></div>
    </dl>
  </PanelCard>
</template>

<style scoped>
.detail {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: var(--wm-space-2) var(--wm-space-5);
  margin: 0;
}

.detail__row {
  display: flex;
  justify-content: space-between;
  gap: var(--wm-space-3);
  padding: var(--wm-space-2) 0;
  /* 详情行的 1px 分隔细线（令牌纪律声明的极少数例外） */
  border-bottom: 1px solid var(--wm-border-hairline);
  font-size: 0.85rem;
}

.detail__row dt {
  color: var(--wm-text-muted);
}

.detail__row dd {
  margin: 0;
  color: var(--wm-text-primary);
  font-variant-numeric: tabular-nums;
}

.detail__error {
  margin: 0 0 var(--wm-space-3);
  color: var(--wm-color-danger);
  font-size: 0.85rem;
}
</style>
