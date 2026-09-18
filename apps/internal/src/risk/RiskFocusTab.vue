<script setup lang="ts">
import { onMounted, ref, watch } from "vue";
import { PanelCard } from "@wealth/shared";
import { errorMessage, formatDateTime } from "../format";
import { listRiskFocus } from "./api";
import { FOCUS_TYPES, type FocusType, type RiskFocus } from "./types";
import { focusSourceLabel, type TabSummary } from "./riskView";
import { useTabSummary } from "./useTabSummary";

// 风险关注是只读的：它是别的 Agent 留下的提示记录，要处置就另开工单。
const emit = defineEmits<{ summary: [value: TabSummary] }>();

const focus = ref<RiskFocus[]>([]);
const loading = ref(true);
const focusError = ref("");
const focusTypeFilter = ref<FocusType | "">("");

async function loadFocus(): Promise<void> {
  loading.value = true;
  focusError.value = "";
  try {
    focus.value = await listRiskFocus(focusTypeFilter.value || undefined);
  } catch (error) {
    focus.value = [];
    focusError.value = errorMessage(error, "风险关注加载失败");
  } finally {
    loading.value = false;
  }
}

watch(focusTypeFilter, loadFocus);
onMounted(loadFocus);

useTabSummary(
  (value) => emit("summary", value),
  () => ({
    headline: `类型 ${focusTypeFilter.value || "全部"} · 只读`,
    count: focus.value.length,
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
      <p v-else-if="!loading && !focus.length" class="focus__empty" data-testid="focus-empty">
        暂无风险关注
      </p>

      <el-table v-if="focus.length" :data="focus" data-testid="focus-table">
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
