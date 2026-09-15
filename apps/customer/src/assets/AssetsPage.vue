<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { ApiError } from "@wealth/shared";
import { RISK_LEVEL_LABELS } from "../risk-assessment/grades";
import { getAssets, listTransactions } from "./api";
import type { CustomerAssets, TransactionFilters, TransactionRecord } from "./types";

const HOLDINGS_EMPTY_HINT = "你还没有持有任何产品。买入后这里会列出每一笔持仓的份额、成本、市值与盈亏。";
const TRANSACTIONS_EMPTY_HINT = "没有符合条件的交易记录。可放宽时间范围，或换成全部交易类型再查一次。";

const TRANSACTION_TYPES = ["申购", "赎回"] as const;

const assets = ref<CustomerAssets | null>(null);
const loading = ref(true);
const errorMessage = ref("");

const transactions = ref<TransactionRecord[]>([]);
const transactionsLoading = ref(true);
const transactionsError = ref("");

const filters = reactive<TransactionFilters>({
  start_date: "",
  end_date: "",
  transaction_type: "",
});

const riskLevelText = computed<string>(() => {
  const level = assets.value?.risk_level;
  if (!level) return "尚未测评";
  return `${level} ${RISK_LEVEL_LABELS[level]}`;
});

function filledFilters(): TransactionFilters {
  const next: TransactionFilters = {};
  if (filters.start_date) next.start_date = filters.start_date;
  if (filters.end_date) next.end_date = filters.end_date;
  if (filters.transaction_type) next.transaction_type = filters.transaction_type;
  return next;
}

async function loadAssets() {
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

async function loadTransactions() {
  transactionsLoading.value = true;
  transactionsError.value = "";
  try {
    const payload = await listTransactions(filledFilters());
    transactions.value = payload.transactions;
  } catch (error) {
    transactions.value = [];
    transactionsError.value =
      error instanceof ApiError ? error.message : "交易流水加载失败";
  } finally {
    transactionsLoading.value = false;
  }
}

onMounted(async () => {
  await loadAssets();
  await loadTransactions();
});
</script>

<template>
  <el-card>
    <h1>我的资产</h1>

    <p v-if="errorMessage" role="alert" data-testid="assets-error">{{ errorMessage }}</p>

    <section v-else-if="assets" data-testid="asset-summary">
      <div>
        <span>持仓总市值</span>
        <strong data-testid="total-market-value">{{ assets.total_market_value }}</strong>
        <span>元</span>
      </div>
      <div>
        <span>持仓只数</span>
        <strong data-testid="holding-count">{{ assets.holding_count }}</strong>
        <span>只</span>
      </div>
      <div>
        <span>风险承受等级</span>
        <strong data-testid="risk-level">{{ riskLevelText }}</strong>
      </div>
      <p v-if="assets.risk_level_valid_until">
        测评有效期至 {{ assets.risk_level_valid_until }}
      </p>
    </section>

    <h2>持仓明细</h2>

    <p v-if="loading">正在加载持仓…</p>
    <p v-else-if="!assets">持仓信息暂不可用</p>
    <p v-else-if="assets.holdings.length === 0" data-testid="holdings-empty">
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
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="holding in assets.holdings"
            :key="holding.product_code"
            :data-product-code="holding.product_code"
          >
            <td>{{ holding.product_name }}（{{ holding.product_code }}）</td>
            <td>{{ holding.product_type }}</td>
            <td>{{ holding.shares }}</td>
            <td>{{ holding.cost_amount }}</td>
            <td>{{ holding.market_value }}</td>
            <td>{{ holding.profit_loss }}</td>
            <td>{{ holding.profit_ratio }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <h2>交易流水</h2>

    <form @submit.prevent="loadTransactions">
      <label>
        起始日期
        <input name="start_date" type="date" v-model="filters.start_date" />
      </label>
      <label>
        截止日期
        <input name="end_date" type="date" v-model="filters.end_date" />
      </label>
      <label>
        交易类型
        <select name="transaction_type" v-model="filters.transaction_type">
          <option value="">全部</option>
          <option v-for="type in TRANSACTION_TYPES" :key="type" :value="type">{{ type }}</option>
        </select>
      </label>
      <el-button
        name="apply-transaction-filters"
        native-type="submit"
        :loading="transactionsLoading"
      >
        筛选
      </el-button>
    </form>

    <p v-if="transactionsLoading">正在加载交易流水…</p>
    <p v-else-if="transactionsError" role="alert" data-testid="transactions-error">
      {{ transactionsError }}
    </p>
    <p v-else-if="transactions.length === 0" data-testid="transactions-empty">
      {{ TRANSACTIONS_EMPTY_HINT }}
    </p>

    <div v-else class="table-wrap">
      <table data-testid="transactions-table">
        <thead>
          <tr>
            <th>流水号</th>
            <th>成交时间</th>
            <th>产品</th>
            <th>类型</th>
            <th>金额（元）</th>
            <th>份额</th>
            <th>成交净值</th>
            <th>手续费（元）</th>
            <th>状态</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in transactions" :key="row.transaction_no">
            <td>{{ row.transaction_no }}</td>
            <td>{{ row.traded_at }}</td>
            <td>{{ row.product_name }}（{{ row.product_code }}）</td>
            <td>{{ row.transaction_type }}</td>
            <td>{{ row.amount }}</td>
            <td>{{ row.shares }}</td>
            <td>{{ row.nav }}</td>
            <td>{{ row.fee }}</td>
            <td>{{ row.status }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </el-card>
</template>

<style scoped>
form {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem 1rem;
  align-items: flex-end;
  margin: 1rem 0;
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
  text-align: left;
  padding: 0.5rem 0.75rem;
  border-bottom: 1px solid var(--el-border-color-lighter);
  white-space: nowrap;
}
</style>
