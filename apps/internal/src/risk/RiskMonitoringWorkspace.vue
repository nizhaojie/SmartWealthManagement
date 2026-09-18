<script setup lang="ts">
import { computed, reactive, ref } from "vue";
import { PageHeader } from "@wealth/shared";
import SummaryCard from "../inspector/SummaryCard.vue";
import { useInspector } from "../shell/pageSlots";
import AlertsTab from "./AlertsTab.vue";
import RiskFocusTab from "./RiskFocusTab.vue";
import RiskQueryTab from "./RiskQueryTab.vue";
import RiskRulesTab from "./RiskRulesTab.vue";
import type { TabSummary } from "./riskView";

type TabKey = "alerts" | "focus" | "rules" | "query";

const TAB_LABELS: Record<TabKey, string> = {
  alerts: "预警列表",
  focus: "风险关注",
  rules: "规则管理",
  query: "自然语言查询",
};

// 工单已拆成一级模块：这里只剩四个页签。
const activeTab = ref<TabKey>("alerts");

// 每个页签把「筛了什么、剩几条」写回自己那一格，检查器只读当前页签那一格。
const summaries = reactive<Record<TabKey, TabSummary>>({
  alerts: { headline: "全部预警", count: null },
  focus: { headline: "全部风险关注", count: null },
  rules: { headline: "规则加载中", count: null },
  query: { headline: "尚未提问", count: null },
});

const activeSummary = computed(() => summaries[activeTab.value]);

function setSummary(tab: TabKey, value: TabSummary): void {
  summaries[tab] = value;
}

// 注入模块自己的筛选摘要（右侧检查器）：当前页签 + 筛了什么 + 剩几条。
useInspector(() => ({
  component: SummaryCard,
  props: {
    title: "风控监测",
    rows: [
      { label: "当前页签", value: TAB_LABELS[activeTab.value], testId: "risk-summary-tab" },
      { label: "筛选摘要", value: activeSummary.value.headline, testId: "risk-summary-filters" },
      {
        label: "当前列表",
        value: activeSummary.value.count === null ? "—" : `${activeSummary.value.count} 条`,
        testId: "risk-summary-count",
      },
    ],
    note: "处置（排除 / 升级 / 派生工单）只对风控专员开放；客户经理只看得到名下客户。",
  },
}));
</script>

<template>
  <div class="risk">
    <PageHeader title="风控监测" :breadcrumb="['风控监测']" />

    <el-tabs v-model="activeTab" class="risk__tabs">
      <el-tab-pane label="预警列表" name="alerts">
        <AlertsTab @summary="setSummary('alerts', $event)" />
      </el-tab-pane>
      <el-tab-pane label="风险关注" name="focus" lazy>
        <RiskFocusTab @summary="setSummary('focus', $event)" />
      </el-tab-pane>
      <el-tab-pane label="规则管理" name="rules" lazy>
        <RiskRulesTab @summary="setSummary('rules', $event)" />
      </el-tab-pane>
      <el-tab-pane label="自然语言查询" name="query" lazy>
        <RiskQueryTab @summary="setSummary('query', $event)" />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<style scoped>
.risk {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-4);
}

.risk__tabs :deep(.el-tabs__header) {
  margin-bottom: var(--wm-space-4);
}
</style>
