<script setup lang="ts">
import { computed } from "vue";
import { ChartFrame, toBarOption } from "@wealth/shared";
import { buildRiskLevelDistribution } from "./allocation";
import type { Holding } from "./types";

const props = withDefaults(defineProps<{ holdings: Holding[]; loading?: boolean }>(), {
  loading: false,
});

const EMPTY_HINT = "还没有可以统计的持仓。买入后这里会画出你的持仓在各产品风险等级上的分布。";

const option = computed(() => toBarOption(buildRiskLevelDistribution(props.holdings)));
</script>

<template>
  <ChartFrame
    title="持仓按产品风险等级的分布"
    hint="类别按 R1 到 R5 排列，可以看整体风险偏向哪一侧。"
    :option="option"
    :loading="loading"
    :empty-text="EMPTY_HINT"
    :height="280"
  />
</template>
