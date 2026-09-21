<script setup lang="ts">
// 交易流水：按时间与类型筛选自己的每一笔资金操作（申购、赎回、转账），用来核对账目。
// 三类记录合并在一张表里读，形状由服务端统一（转账行没有产品名而有收款人）。
import { onMounted, reactive, ref } from "vue";
import { ApiError, PanelCard } from "@wealth/shared";
import { listTransactions } from "./api";
import type { TransactionFilters, TransactionRecord } from "./types";

const EMPTY_HINT = "没有符合条件的交易记录。可放宽时间范围，或换成全部交易类型再查一次。";

// 三类记录并排在同一张表里：转账是唯一的没有产品、有收款人的那一类（ADR-0019）。
const TRANSACTION_TYPES = ["申购", "赎回", "转账"] as const;

/** 转账没有产品，申赎没有收款人：缺失的一项显示为「—」，不编造、也不留空单元格。 */
function productLabel(row: TransactionRecord): string {
  return row.product_name && row.product_code
    ? `${row.product_name}（${row.product_code}）`
    : "—";
}

function payeeLabel(row: TransactionRecord): string {
  return row.payee_name ? `${row.payee_name}（${row.payee_account ?? "—"}）` : "—";
}

const transactions = ref<TransactionRecord[]>([]);
const loading = ref(true);
const errorMessage = ref("");

const filters = reactive<TransactionFilters>({
  start_date: null,
  end_date: null,
  transaction_type: "",
});

async function load(): Promise<void> {
  loading.value = true;
  errorMessage.value = "";
  try {
    // 空条件由 api 层统一去掉，这里照原样传。
    transactions.value = (await listTransactions(filters)).transactions;
  } catch (error) {
    transactions.value = [];
    errorMessage.value = error instanceof ApiError ? error.message : "交易流水加载失败";
  } finally {
    loading.value = false;
  }
}

onMounted(load);
</script>

<template>
  <PanelCard title="交易流水">
    <form class="filters" @submit.prevent="load">
      <label class="filters__field">
        <span class="filters__label">起始日期</span>
        <el-date-picker
          v-model="filters.start_date"
          type="date"
          value-format="YYYY-MM-DD"
          placeholder="选择起始日期"
          clearable
        />
      </label>
      <label class="filters__field">
        <span class="filters__label">截止日期</span>
        <el-date-picker
          v-model="filters.end_date"
          type="date"
          value-format="YYYY-MM-DD"
          placeholder="选择截止日期"
          clearable
        />
      </label>
      <label class="filters__field">
        <span class="filters__label">交易类型</span>
        <el-select v-model="filters.transaction_type" name="transaction_type" placeholder="全部" placement="top-start">
          <el-option label="全部" value="" />
          <el-option v-for="type in TRANSACTION_TYPES" :key="type" :label="type" :value="type" />
        </el-select>
      </label>
      <el-button name="apply-transaction-filters" native-type="submit" :loading="loading">
        筛选
      </el-button>
    </form>

    <p v-if="loading" class="history__status">正在加载交易流水…</p>
    <p
      v-else-if="errorMessage"
      class="history__error"
      role="alert"
      data-testid="transactions-error"
    >
      {{ errorMessage }}
    </p>
    <p v-else-if="transactions.length === 0" class="history__status" data-testid="transactions-empty">
      {{ EMPTY_HINT }}
    </p>

    <div v-else class="table-wrap">
      <table data-testid="transactions-table">
        <thead>
          <tr>
            <th>流水号</th>
            <th>成交时间</th>
            <th>产品</th>
            <th>收款人</th>
            <th>类型</th>
            <th>金额（元）</th>
            <th>份额</th>
            <th>成交净值</th>
            <th>手续费（元）</th>
            <th>状态</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in transactions"
            :key="row.transaction_no"
            :data-transaction-type="row.transaction_type"
          >
            <td>{{ row.transaction_no }}</td>
            <td>{{ row.traded_at }}</td>
            <td>{{ productLabel(row) }}</td>
            <td>{{ payeeLabel(row) }}</td>
            <td>{{ row.transaction_type }}</td>
            <td>{{ row.amount }}</td>
            <td>{{ row.shares ?? "—" }}</td>
            <td>{{ row.nav ?? "—" }}</td>
            <td>{{ row.fee ?? "—" }}</td>
            <td>{{ row.status }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </PanelCard>
</template>

<style scoped>
.filters {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: var(--wm-space-3) var(--wm-space-4);
  margin-bottom: var(--wm-space-4);
}

.filters__field {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-1);
  min-width: calc(var(--wm-space-6) * 5);
}

.filters__label {
  color: var(--wm-text-muted);
  font-size: 0.8rem;
}

/* 日期与类型筛选用组件库控件，统一描边与触发方式 */
.filters :deep(.el-date-editor) {
  width: calc(var(--wm-space-6) * 5);
}

.filters :deep(.el-select) {
  width: calc(var(--wm-space-6) * 5);
}

.history__status {
  margin: 0;
  color: var(--wm-text-muted);
  font-size: 0.85rem;
}

.history__error {
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
</style>
