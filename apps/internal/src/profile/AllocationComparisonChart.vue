<script setup lang="ts">
import { computed } from "vue";
import { ChartFrame, toComparisonBarOption } from "@wealth/shared";
import { actualAllocationSeries, targetAllocationSeries } from "./allocation";
import type { Holding } from "./types";

// 配置对比图：目标配置与实际配置站在同一根类别轴上（ADR-0006）。
// 形状函数来自 shared 的 chart/*，这里只负责把画像与持仓翻成两组序列。
const props = defineProps<{
  targetAllocation: Record<string, number> | null;
  holdings: Holding[];
  loading?: boolean;
}>();

const option = computed(() =>
  toComparisonBarOption([
    { name: "目标配置", data: targetAllocationSeries(props.targetAllocation ?? {}) },
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
    :height="220"
    empty-text="还没有目标配置或持仓数据，无法画出对比图。"
  />
</template>
