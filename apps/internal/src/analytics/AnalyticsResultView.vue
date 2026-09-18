<script setup lang="ts">
import { computed, ref } from "vue";
import { PanelCard } from "@wealth/shared";
import { toCsv } from "./csv";
import type { AnalyticsQueryResponse } from "./types";

// 受限查询的结果呈现：解读 + 表格 + 折叠的 SQL + CSV 导出 + 截断提示。
// 截断提示常写常显（截断时），不让「只看到前 N 行」这件事藏在表格滚动里。
const props = defineProps<{ result: AnalyticsQueryResponse }>();

const showSql = ref(false);

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
  <PanelCard title="查询结果">
    <template #actions>
      <el-button size="small" name="toggle-sql" data-testid="toggle-sql" @click="showSql = !showSql">
        {{ showSql ? "收起生成的查询" : "查看生成的查询" }}
      </el-button>
      <el-button size="small" name="export-csv" data-testid="export-csv" @click="exportCsv">
        导出 CSV
      </el-button>
    </template>

    <p class="result__interpretation" data-testid="interpretation">
      {{ result.interpretation }}
    </p>

    <el-alert
      v-if="result.disclaimer"
      class="result__disclaimer"
      type="warning"
      :closable="false"
      :title="result.disclaimer"
      data-testid="disclaimer"
    />

    <p v-if="result.truncated" class="result__truncation" data-testid="truncation-notice">
      结果超过行数上限，已截断：仅显示前 {{ result.row_count }} 行，并非全量。
    </p>

    <p class="result__meta">
      共 {{ result.row_count }} 行 · 涉及 {{ result.views.join("、") }}
    </p>

    <pre v-if="showSql" class="result__sql" data-testid="sql-block">{{ result.sql }}</pre>

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
  </PanelCard>
</template>

<style scoped>
.result__interpretation {
  margin: 0 0 var(--wm-space-3);
  color: var(--wm-text-primary);
  font-size: 0.9rem;
  line-height: 1.8;
}

.result__disclaimer {
  margin-bottom: var(--wm-space-3);
}

.result__truncation {
  margin: 0 0 var(--wm-space-2);
  color: var(--wm-color-warning);
  font-size: 0.82rem;
  line-height: 1.7;
}

.result__meta {
  margin: 0 0 var(--wm-space-3);
  color: var(--wm-text-muted);
  font-size: 0.8rem;
  font-variant-numeric: tabular-nums;
}

.result__sql {
  margin: 0 0 var(--wm-space-3);
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

.result__table {
  overflow-x: auto;
}
</style>
