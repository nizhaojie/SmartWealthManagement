<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { ApiError, PageHeader, PanelCard, StatCard } from "@wealth/shared";
import { RISK_LEVEL_LABELS } from "../risk-assessment/grades";
import ActualAllocationChart from "./ActualAllocationChart.vue";
import HoldingLookThrough from "./HoldingLookThrough.vue";
import RiskLevelDistributionChart from "./RiskLevelDistributionChart.vue";
import TransactionHistory from "./TransactionHistory.vue";
import { getAssets, getHoldingLookThrough } from "./api";
import { profitClass } from "./profit";
import type { CustomerAssets, LookThrough } from "./types";

const HOLDINGS_EMPTY_HINT =
  "你还没有持有任何产品。买入后这里会列出每一笔持仓的份额、成本、市值与盈亏。";

const assets = ref<CustomerAssets | null>(null);
const loading = ref(true);
const errorMessage = ref("");

const openedLookThrough = ref("");
const lookThroughs = ref<Record<string, LookThrough>>({});
const lookThroughLoading = ref("");
const lookThroughError = ref("");

const holdings = computed(() => assets.value?.holdings ?? []);
const totalMarketValue = computed(() => assets.value?.total_market_value ?? "—");
const holdingCount = computed(() => (assets.value ? String(assets.value.holding_count) : "—"));

const riskLevelText = computed<string>(() => {
  const level = assets.value?.risk_level;
  if (!level) return "尚未测评";
  return `${level} ${RISK_LEVEL_LABELS[level]}`;
});

async function loadAssets(): Promise<void> {
  loading.value = true;
  errorMessage.value = "";
  try {
    assets.value = await getAssets();
  } catch (error) {
    assets.value = null;
    errorMessage.value = error instanceof ApiError ? error.message : "资产信息加载失败";
  } finally {
    loading.value = false;
  }
}

async function toggleLookThrough(productCode: string): Promise<void> {
  if (openedLookThrough.value === productCode) {
    openedLookThrough.value = "";
    lookThroughError.value = "";
    return;
  }
  openedLookThrough.value = productCode;
  lookThroughError.value = "";
  if (lookThroughs.value[productCode]) {
    return;
  }

  lookThroughLoading.value = productCode;
  try {
    lookThroughs.value = {
      ...lookThroughs.value,
      [productCode]: await getHoldingLookThrough(productCode),
    };
  } catch (error) {
    lookThroughError.value = error instanceof ApiError ? error.message : "持仓穿透加载失败";
  } finally {
    lookThroughLoading.value = "";
  }
}

onMounted(loadAssets);
</script>

<template>
  <div class="assets">
    <PageHeader title="我的资产" :breadcrumb="['客户视图', '我的资产']" />

    <p v-if="errorMessage" class="assets__error" role="alert" data-testid="assets-error">
      {{ errorMessage }}
    </p>

    <div v-else class="assets__stats" data-testid="asset-summary">
      <StatCard title="持仓总市值（元）" :value="totalMarketValue" accent="primary" />
      <StatCard title="持仓只数" :value="holdingCount" accent="primary" />
      <StatCard title="风险承受等级" :value="riskLevelText" accent="primary" />
    </div>

    <p v-if="assets?.risk_level_valid_until" class="assets__validity">
      测评有效期至 {{ assets.risk_level_valid_until }}
    </p>

    <div class="assets__charts">
      <ActualAllocationChart :holdings="holdings" :loading="loading" />
      <RiskLevelDistributionChart :holdings="holdings" :loading="loading" />
    </div>

    <PanelCard title="持仓明细">
      <p v-if="loading" class="assets__status">正在加载持仓…</p>
      <p v-else-if="!assets" class="assets__status">持仓信息暂不可用</p>
      <p v-else-if="holdings.length === 0" class="assets__status" data-testid="holdings-empty">
        {{ HOLDINGS_EMPTY_HINT }}
      </p>

      <div v-else class="table-wrap">
        <table data-testid="holdings-table">
          <thead>
            <tr>
              <th>产品</th>
              <th>类型</th>
              <th>份额</th>
              <th>成本（元）</th>
              <th>市值（元）</th>
              <th>盈亏（元）</th>
              <th>盈亏比例（%）</th>
              <th>底层</th>
            </tr>
          </thead>
          <tbody>
            <template v-for="holding in holdings" :key="holding.product_code">
              <tr :data-product-code="holding.product_code">
                <td>{{ holding.product_name }}（{{ holding.product_code }}）</td>
                <td>{{ holding.product_type }}</td>
                <td>{{ holding.shares }}</td>
                <td>{{ holding.cost_amount }}</td>
                <td>{{ holding.market_value }}</td>
                <td :class="profitClass(holding.profit_loss)">{{ holding.profit_loss }}</td>
                <td :class="profitClass(holding.profit_ratio)">{{ holding.profit_ratio }}</td>
                <td>
                  <el-button
                    size="small"
                    data-testid="look-through-entry"
                    :data-product-code="holding.product_code"
                    @click="toggleLookThrough(holding.product_code)"
                  >
                    {{ openedLookThrough === holding.product_code ? "收起穿透" : "展开穿透" }}
                  </el-button>
                </td>
              </tr>
              <tr v-if="openedLookThrough === holding.product_code">
                <td colspan="8">
                  <p v-if="lookThroughLoading === holding.product_code" class="assets__status">
                    正在穿透…
                  </p>
                  <p
                    v-else-if="lookThroughError"
                    class="assets__error"
                    role="alert"
                    data-testid="look-through-error"
                  >
                    {{ lookThroughError }}
                  </p>
                  <HoldingLookThrough
                    v-else-if="lookThroughs[holding.product_code]"
                    :look-through="lookThroughs[holding.product_code]"
                  />
                </td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>
    </PanelCard>

    <TransactionHistory />
  </div>
</template>

<style scoped>
.assets {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-4);
}

.assets__stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(calc(var(--wm-space-6) * 7), 1fr));
  gap: var(--wm-space-4);
}

.assets__charts {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(calc(var(--wm-space-6) * 10), 1fr));
  gap: var(--wm-space-4);
}

.assets__validity,
.assets__status {
  margin: 0;
  color: var(--wm-text-muted);
  font-size: 0.85rem;
}

.assets__error {
  margin: 0;
  color: var(--wm-color-danger);
  font-size: 0.85rem;
}

.table-wrap {
  overflow-x: auto;
}

table {
  width: 100%;
  border-collapse: collapse;
}

th,
td {
  padding: var(--wm-space-2) var(--wm-space-3);
  /* 表格行的 1px 分隔细线（令牌纪律声明的极少数例外） */
  border-bottom: 1px solid var(--wm-border-hairline);
  text-align: left;
  font-size: 0.85rem;
  white-space: nowrap;
}

th {
  color: var(--wm-text-muted);
  font-weight: 600;
}

td {
  color: var(--wm-text-primary);
  font-variant-numeric: tabular-nums;
}

/* 红涨绿跌：颜色唯一出处是令牌，这里只按符号挂类名 */
.profit-up {
  color: var(--wm-color-up);
}

.profit-down {
  color: var(--wm-color-down);
}
</style>
