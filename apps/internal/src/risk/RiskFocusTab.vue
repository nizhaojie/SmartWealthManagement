<script setup lang="ts">
// 风险关注是只读的：它是别的 Agent 留下的提示记录，要处置就另开工单。
//
// 分页由 `usePagination` 接管（ADR-0024）：改类型筛选是「换了一批数据」，回到第一页
// 再取；翻页只换页码，筛选条件留在表单里不动。
import { onMounted, ref, watch } from "vue";
import { PaginationBar, PanelCard, usePagination } from "@wealth/shared";
import { formatDateTime } from "../format";
import { listRiskFocus } from "./api";
import { FOCUS_TYPES, type FocusType, type RiskFocus } from "./types";
import { focusSourceLabel, type TabSummary } from "./riskView";
import { useTabSummary } from "./useTabSummary";

const emit = defineEmits<{ summary: [value: TabSummary] }>();

const focusTypeFilter = ref<FocusType | "">("");

const {
  items,
  total,
  page,
  pageSize,
  loading,
  errorMessage: focusError,
  goTo,
  reset,
} = usePagination<RiskFocus>(
  (query) => listRiskFocus({ focusType: focusTypeFilter.value || undefined }, query),
  { failureMessage: "风险关注加载失败" },
);

watch(focusTypeFilter, reset);
onMounted(() => {
  void reset();
});

useTabSummary(
  (value) => emit("summary", value),
  () => ({
    headline: `类型 ${focusTypeFilter.value || "全部"} · 只读`,
    count: total.value,
  }),
);
</script>

<template>
  <div class="focus">
    <PanelCard title="筛选">
      <label class="focus__field">
        <span class="focus__label">类型</span>
        <el-select
          v-model="focusTypeFilter"
          name="focus-type"
          placeholder="全部"
          data-testid="focus-type-filter"
        >
          <el-option label="全部" value="" />
          <el-option v-for="type in FOCUS_TYPES" :key="type" :label="type" :value="type" />
        </el-select>
      </label>
    </PanelCard>

    <PanelCard title="风险关注">
      <p v-if="focusError" class="focus__error" role="alert" data-testid="focus-error">
        {{ focusError }}
      </p>
      <p v-else-if="!loading && !items.length" class="focus__empty" data-testid="focus-empty">
        暂无风险关注
      </p>

      <el-table v-if="items.length" :data="items" data-testid="focus-table">
        <el-table-column label="时间" width="180">
          <template #default="{ row }">{{ formatDateTime(row.occurred_at) }}</template>
        </el-table-column>
        <el-table-column label="客户" prop="customer_name" min-width="110" />
        <el-table-column label="类型" prop="focus_type" width="120" />
        <el-table-column label="等级" width="90">
          <template #default="{ row }">{{ row.severity ?? "—" }}</template>
        </el-table-column>
        <el-table-column label="理由" prop="reason" min-width="220" />
        <el-table-column label="来源" width="160">
          <template #default="{ row }">{{ focusSourceLabel(row.source) }}</template>
        </el-table-column>
      </el-table>

      <!-- 取不到时 `total` 归零，分页条与表格同进同退：没有记录时它不该出现。 -->
      <PaginationBar
        v-if="total > 0"
        :total="total"
        :page="page"
        :page-size="pageSize"
        :disabled="loading"
        @update:page="goTo"
      />
    </PanelCard>
  </div>
</template>

<style scoped>
.focus {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-4);
}

.focus__field {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-1);
  min-width: calc(var(--wm-space-6) * 5);
}

.focus__label {
  color: var(--wm-text-muted);
  font-size: 0.8rem;
}

.focus__error {
  margin: 0;
  color: var(--wm-color-danger);
  font-size: 0.85rem;
}

.focus__empty {
  margin: 0;
  color: var(--wm-text-muted);
  font-size: 0.85rem;
}
</style>
