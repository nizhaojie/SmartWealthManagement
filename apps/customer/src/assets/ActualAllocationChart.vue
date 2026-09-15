<script setup lang="ts">
import { ChartFrame, toDonutOption } from "@wealth/shared";
import { computed } from "vue";
import { buildActualAllocation } from "./allocation";
import type { Holding } from "./types";

const props = withDefaults(defineProps<{ holdings: Holding[]; loading?: boolean }>(), {
  loading: false,
});

const EMPTY_HINT = "还没有可以统计的持仓。买入后这里会画出你的钱实际分布在哪几类资产上。";

const option = computed(() => toDonutOption(buildActualAllocation(props.holdings)));
</script>

<template>
  <ChartFrame
    title="实际配置"
    hint="按当前持仓的市值聚合，是你已经持有的比例。"
    :option="option"
    :loading="loading"
    :empty-text="EMPTY_HINT"
    :height="280"
  />
</template>
