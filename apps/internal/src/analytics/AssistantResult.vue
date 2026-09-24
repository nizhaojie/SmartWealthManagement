<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { toCsv } from "./csv";
import type { AnalyticsQueryResponse } from "./types";

// 助手气泡里的结果面：结果表 → 可折叠 SQL → 贴底的元信息行，外加免责与截断两处提示。
// 次序是 spec 定下的固定次序（口径解读由气泡上层渲染，不在这一件里）。
//
// 只服务数据分析这一页：风控问答继续用 `AnalyticsResultView.vue`（Q4 明说原样不动）。
// 两者形似，但一个是卡片里的结果区、一个是对话气泡里的产物，各有各的外框。
const props = defineProps<{ result: AnalyticsQueryResponse }>();
const emit = defineEmits<{ grow: [] }>();

// SQL 是「这句话被翻译成了什么」的凭证：要能查，但不该抢在结果前面，默认折叠。
const showSql = ref(false);

// 展开那一刻气泡会变高：报一声，线程才把这一段带进可视区。
watch(showSql, (open) => {
  if (open) emit("grow");
});

// 列由后端给（`columns`），行是拉链式的二维数组（`rows`）：配成对象才是表格要的形状。
const tableData = computed(() =>
  props.result.rows.map((row) => {
    const item: Record<string, unknown> = {};
    props.result.columns.forEach((column, index) => {
      item[column] = row[index];
    });
    return item;
  }),
);

function exportCsv(): void {
  // CSV 的拼装与 BOM 复用 `csv.ts`；下载那几行与 `AnalyticsResultView` 是同形不同源——
  // 风控那一件这次不动（Q4），不为 6 行样板去动它。
  const csv = toCsv(props.result.columns, props.result.rows);
  // BOM 让 Excel 认出 UTF-8，不然中文列名会乱码。
  const blob = new Blob([`\ufeff${csv}`], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `analytics-${Date.now()}.csv`;
  link.click();
  URL.revokeObjectURL(url);
}
</script>

<template>
  <div class="result">
    <!-- 免责声明是投顾内容的合规呈现面：只有它非空时才在（纯内部数据查询不带）。 -->
    <el-alert
      v-if="result.disclaimer"
      type="warning"
      :closable="false"
      :title="result.disclaimer"
      data-testid="disclaimer"
    />

    <div class="result__table">
      <el-table :data="tableData" data-testid="result-table">
        <el-table-column
          v-for="column in result.columns"
          :key="column"
          :label="column"
          :prop="column"
          min-width="120"
        />
      </el-table>
    </div>

    <!-- 截断常写常显：不让「只看到前 N 行」这件事藏在表格滚动里。 -->
    <p v-if="result.truncated" class="result__truncation" data-testid="truncation-notice">
      结果超过行数上限，已截断：仅显示前 {{ result.row_count }} 行，并非全量。
    </p>

    <div class="result__sql">
      <el-button size="small" name="toggle-sql" data-testid="toggle-sql" @click="showSql = !showSql">
        {{ showSql ? "收起生成的查询" : "查看生成的查询" }}
      </el-button>
      <pre v-if="showSql" class="result__sql-code" data-testid="sql-block">{{ result.sql }}</pre>
    </div>

    <div class="result__meta">
      <p class="result__meta-line" data-testid="result-meta">共 {{ result.row_count }} 行 · 涉及 {{ result.views.join("、") }}</p>
      <el-button size="small" name="export-csv" data-testid="export-csv" @click="exportCsv">
        导出 CSV
      </el-button>
    </div>
  </div>
</template>

<style scoped>
.result {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-3);
}

/* 宽表是这页的常态（主区在重做时为此取消了限宽）：横向滑动只发生在表格这一格 */
.result__table {
  overflow-x: auto;
}

.result__truncation {
  margin: 0;
  color: var(--wm-color-warning);
  font-size: 0.82rem;
  line-height: 1.7;
}

.result__sql {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--wm-space-2);
}

.result__sql-code {
  margin: 0;
  width: 100%;
  padding: var(--wm-space-3);
  border-radius: var(--wm-radius-sm);
  background-color: var(--wm-bg-subtle);
  color: var(--wm-text-primary);
  font-family: var(--wm-font-mono);
  font-size: 0.78rem;
  line-height: 1.7;
  overflow-x: auto;
  white-space: pre-wrap;
}

/* 元信息行贴底：一条细线与上方的产物分开，左边是说数、右边是出口 */
.result__meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--wm-space-3);
  padding-top: var(--wm-space-3);
  /* 细线属令牌纪律声明的极少数 1px 例外 */
  border-top: 1px solid var(--wm-border-hairline);
}

.result__meta-line {
  margin: 0;
  color: var(--wm-text-muted);
  font-size: 0.8rem;
  font-variant-numeric: tabular-nums;
}
</style>
