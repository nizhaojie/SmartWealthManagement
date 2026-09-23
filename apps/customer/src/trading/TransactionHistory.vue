<script setup lang="ts">
// 交易流水：按时间与类型筛选自己的每一笔资金操作（申购、赎回、转账、充值），用来核对账目。
// 四类记录合并在一张表里读，形状由服务端统一（转账行没有产品名而有收款人，充值行两者皆无）。
//
// 列表分页由 `usePagination` 接管（ADR-0024）：翻页只换页码，筛选条件留在表单里不动；
// 反过来，改筛选是「换了一批数据」而不是「看第 3 页」，所以筛选一提交就回到第一页——
// 停在第 3 页会看到空表，而那不是筛选的结果。
import { onMounted, reactive } from "vue";
import { formatDateTime, PaginationBar, PanelCard, usePagination } from "@wealth/shared";
import { listTransactions } from "./api";
import type { TransactionFilters, TransactionRecord } from "./types";

const EMPTY_HINT = "没有符合条件的交易记录。可放宽时间范围，或换成全部交易类型再查一次。";

// 四类记录并排在同一张表里：转账与充值都没有产品，其中只有转账有收款人（ADR-0019、ADR-0023）。
const TRANSACTION_TYPES = ["申购", "赎回", "转账", "充值"] as const;

/** 产品位只对申赎成立、收款人位只对转账成立：缺失的一项显示为「—」，不编造、也不留空单元格。 */
function productLabel(row: TransactionRecord): string {
  return row.product_name && row.product_code
    ? `${row.product_name}（${row.product_code}）`
    : "—";
}

function payeeLabel(row: TransactionRecord): string {
  return row.payee_name ? `${row.payee_name}（${row.payee_account ?? "—"}）` : "—";
}

const filters = reactive<TransactionFilters>({
  start_date: null,
  end_date: null,
  transaction_type: "",
});

// 空条件由 api 层统一去掉，这里照原样传；`filters` 是 reactive，取数时读到的永远是最新的一份。
const { items, total, page, pageSize, loading, errorMessage, goTo, reset } =
  usePagination<TransactionRecord>(
    (query) => listTransactions(filters, query),
    { failureMessage: "交易流水加载失败" },
  );

onMounted(() => {
  void reset();
});
</script>

<template>
  <PanelCard title="交易流水">
    <form class="filters" @submit.prevent="reset">
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
    <p v-else-if="items.length === 0" class="history__status" data-testid="transactions-empty">
      {{ EMPTY_HINT }}
    </p>

    <div v-else class="table-wrap">
      <table data-testid="transactions-table">
        <thead>
          <tr>
            <th>流水号</th>
            <th>成交时间</th>
            <th class="cell--wrap">产品</th>
            <th class="cell--wrap">收款人</th>
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
            v-for="row in items"
            :key="row.transaction_no"
            :data-transaction-type="row.transaction_type"
          >
            <td>{{ row.transaction_no }}</td>
            <td>{{ formatDateTime(row.traded_at) }}</td>
            <td class="cell--wrap">{{ productLabel(row) }}</td>
            <td class="cell--wrap">{{ payeeLabel(row) }}</td>
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

    <!-- 取不到时 `total` 归零，分页条因此与表格同进同退：加载失败或没有流水时都不出现。 -->
    <PaginationBar
      v-if="total > 0"
      :total="total"
      :page="page"
      :page-size="pageSize"
      :disabled="loading"
      @update:page="goTo"
    />
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

/* 兜底：极窄视口下表格仍可横向滚动，但正常情况下表格会收窄到容器内，不出现滚动条。 */
.table-wrap {
  overflow-x: auto;
}

table {
  width: 100%;
  border-collapse: collapse;
}

/*
 * 默认 nowrap：流水号、成交时间、金额这类数据一旦折行就读不出来（「TX2026…」断成两截）。
 * 全表十列都在一行时约 1270px，所以只让产品名与收款人两列折行（.cell--wrap），
 * 其余列保持一行，表格最小宽度才落得进主区——横向滚动条因此不出现。
 * 内边距收到 8px 也是为此：十列各让出 8px，正好把 12px 内边距下差的那几十像素找回来。
 */
th,
td {
  padding: var(--wm-space-2);
  /* 表格行的 1px 分隔细线（令牌纪律声明的极少数例外） */
  border-bottom: 1px solid var(--wm-border-hairline);
  text-align: left;
  font-size: 0.85rem;
  white-space: nowrap;
}

/* 产品名与收款人（含账号）是整表里唯一两段放得下的长文本：折行 + 长串就地断行。 */
.cell--wrap {
  white-space: normal;
  overflow-wrap: anywhere;
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
