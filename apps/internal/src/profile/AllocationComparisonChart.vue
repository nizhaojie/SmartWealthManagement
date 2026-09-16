<script setup lang="ts">
import { ChartFrame, toComparisonBarOption } from "@wealth/shared";
import { computed } from "vue";
import { actualAllocationSeries, targetAllocationSeries } from "./allocation";
import type { Holding } from "./types";

const props = withDefaults(
  defineProps<{
    targetAllocation: Record<string, number>;
    holdings: Holding[];
    loading?: boolean;
  }>(),
  { loading: false },
);

const EMPTY_HINT = "还没有目标配置或持仓数据，无法画出对比图。";

const option = computed(() =>
  toComparisonBarOption([
    { name: "目标配置", data: targetAllocationSeries(props.targetAllocation) },
    { name: "实际配置", data: actualAllocationSeries(props.holdings) },
  ]),
);
</script>

<template>
  <ChartFrame
    title="目标配置 vs 实际配置"
    hint="条形对齐同一基线，末端标出实际相对目标的差值。"
    :option="option"
    :loading="loading"
    :empty-text="EMPTY_HINT"
    :height="220"
  />
</template>
