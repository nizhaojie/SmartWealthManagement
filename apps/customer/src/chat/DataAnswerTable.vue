<script setup lang="ts">
// 数据查询回答里的结果表（ADR-0028）：文本说「这些数字是怎么来的」，表是数字的唯一出处。
//
// 形态对齐客户侧既有的三处表格（`TransactionHistory.vue` 那一类）：原生 `<table>` + `--wm-*`
// 令牌 + `.table-wrap` 横向滚动 + `data-testid`，不走 `el-table`——客户侧 EP 虽是全量注册，
// 但同一个应用里出现两套表格观感不值当。
//
// 实时气泡与历史回看复用这一件：两边看到的必须是同一张表。
//
// `data` 可为空：零行 / 失败 / 白名单外三种出口都不带表，这时整件不渲染——
// 不留空壳（空表会把「没有数据」与「查询挂了」在观感上抹平）。
import { computed } from "vue";
import type { DataAnswer } from "./api";

const props = defineProps<{ data?: DataAnswer | null }>();

/**
 * 拉链式二维数组 → 按列取值。`columns[].key` 是英文列名，只在这一步用来定位值，
 * 界面上出现的只有 `label`（后端给的中文表头）。
 */
const rows = computed<Record<string, unknown>[]>(() => {
  const data = props.data;
  if (!data) {
    return [];
  }
  return data.rows.map((row) => {
    const item: Record<string, unknown> = {};
    data.columns.forEach((column, index) => {
      item[column.key] = row[index];
    });
    return item;
  });
});

/** 缺值统一「—」：与客户侧其余表格同一条约定，空白格会被读成「0」或「没加载出来」。 */
function cell(value: unknown): string {
  return value === null || value === undefined ? "—" : String(value);
}
</script>

<template>
  <section v-if="data" class="data-answer" data-testid="data-answer">
    <div class="table-wrap">
      <table data-testid="data-answer-table">
        <thead>
          <tr>
            <th v-for="column in data.columns" :key="column.key">{{ column.label }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, rowIndex) in rows" :key="rowIndex">
            <td v-for="column in data.columns" :key="column.key">{{ cell(row[column.key]) }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 行数是「这表是全量还是被截了」的一半信息，常写常显；截断那半只在真截断时出现。 -->
    <p class="data-answer__count" data-testid="data-answer-count">共 {{ data.row_count }} 行</p>
    <p
      v-if="data.truncated"
      class="data-answer__truncation"
      data-testid="data-answer-truncation"
    >
      结果超出行数上限，仅显示前 {{ data.row_count }} 行，并非全量。
    </p>
  </section>
</template>

<style scoped>
.data-answer {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-2);
  margin-top: var(--wm-space-3);
}

/* 兜底：列多或值长时表格横向滚动，气泡宽度不被撑破。 */
.table-wrap {
  overflow-x: auto;
}

table {
  width: 100%;
  border-collapse: collapse;
}

/*
 * 默认 nowrap：视图里的列名与值都是「读得出来才有意义」的短单元（产品名、份额、市值），
 * 折行会把一行数据拆成看不懂的两截。列多到放不下时由 .table-wrap 横向滚动接手。
 * 内边距取 8px，与客户侧其余表格同档。
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

th {
  color: var(--wm-text-muted);
  font-weight: 600;
}

/* 与 `TransactionHistory` 同一条做法：整表对齐数字字形，金额列上下对齐才好比对。 */
td {
  color: var(--wm-text-primary);
  font-variant-numeric: tabular-nums;
}

.data-answer__count {
  margin: 0;
  color: var(--wm-text-muted);
  font-size: 0.75rem;
}

.data-answer__truncation {
  margin: 0;
  color: var(--wm-color-warning);
  font-size: 0.75rem;
}
</style>
