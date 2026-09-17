\ufeff<script setup lang="ts">
import { computed, ref } from "vue";
import { SectionCard } from "@wealth/shared";
import { toCsv } from "./csv";
import type { AnalyticsQueryResponse } from "./types";

const props = defineProps<{ result: AnalyticsQueryResponse }>();

// 生成的查询默认折叠：员工需要时能展开判断系统有没有理解自己的问题，
// 但多数时候不想看 SQL。
const showSql = ref(false);

const tableData = computed(() =>
  props.result.rows.map((row) =>
    Object.fromEntries(props.result.columns.map((column, index) => [column, row[index]])),
  ),
);

function exportCsv() {
  // BOM 让 Excel 正确识别 UTF-8 中文。
  const blob = new Blob(["\uFEFF" + toCsv(props.result.columns, props.result.rows)], {
    type: "text/csv;charset=utf-8",
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `analytics-${Date.now()}.csv`;
  link.click();
  URL.revokeObjectURL(url);
}
</script>

<template>
  <SectionCard title="查询结果" class="analytics-result">
    <p class="analytics-result__interpretation" data-test="interpretation">
      {{ result.interpretation }}
    </p>
    <p v-if="result.disclaimer" class="analytics-result__disclaimer" data-test="disclaimer">
      {{ result.disclaimer }}
    </p>

    <el-alert
      v-if="result.truncated"
      type="warning"
      :closable="false"
      class="analytics-result__truncated"
      data-test="truncation-notice"
      :title="`结果超过行数上限，已截断：仅显示前 ${result.row_count} 行，并非全量。`"
    />

    <div class="analytics-result__toolbar">
      <el-button size="small" data-test="toggle-sql" @click="showSql = !showSql">
        {{ showSql ? "收起生成的查询" : "查看生成的查询" }}
      </el-button>
      <el-button size="small" data-test="export-csv" @click="exportCsv">导出 CSV</el-button>
      <span class="analytics-result__meta">
        共 {{ result.row_count }} 行 · 涉及 {{ result.views.join("、") }}
      </span>
    </div>
    <pre v-if="showSql" class="analytics-result__sql" data-test="sql-block">{{ result.sql }}</pre>

    <el-table :data="tableData" data-test="result-table" border>
      <el-table-column
        v-for="column in result.columns"
        :key="column"
        :prop="column"
        :label="column"
      />
    </el-table>
  </SectionCard>
</template>

<style scoped>
.analytics-result__interpretation {
  margin-top: 0;
  line-height: 1.7;
  color: var(--wm-text-primary);
}

/* 免责声明用 warning 淡染底：底色由令牌现场混白派生，不存裸色值 */
.analytics-result__disclaimer {
  padding: var(--wm-space-2) var(--wm-space-3);
  background: color-mix(in srgb, var(--wm-color-warning) 8%, var(--wm-bg-card));
  /* 3px warning 左条：提示条规格，同 StatCard 左条（非 1px 细线例外） */
  border-left: 3px solid var(--wm-color-warning);
  color: var(--wm-color-warning);
  font-size: 13px;
}

.analytics-result__toolbar {
  display: flex;
  align-items: center;
  gap: var(--wm-space-3);
  margin: var(--wm-space-3) 0;
}

.analytics-result__meta {
  color: var(--wm-text-muted);
  font-size: 12px;
}

.analytics-result__sql {
  background: var(--wm-bg-page);
  padding: var(--wm-space-3);
  overflow-x: auto;
  font-size: 13px;
  color: var(--wm-text-secondary);
}

.analytics-result__truncated {
  margin-bottom: var(--wm-space-3);
}
</style>
