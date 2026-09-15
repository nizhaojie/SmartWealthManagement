<script setup lang="ts">
// 图表壳：只管实例生命周期、尺寸自适应、加载态与空状态，不知道画的是什么。
// 调用方传一个配置进来，壳负责把它画上、跟着容器变、没东西可画时给出解释。

import { nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { echarts } from "./echarts";
import type { ChartInstance } from "./echarts";
import type { ChartOption } from "./options";

const props = withDefaults(
  defineProps<{
    option: ChartOption | null;
    title?: string;
    hint?: string;
    loading?: boolean;
    emptyText?: string;
    height?: number;
  }>(),
  {
    title: "",
    hint: "",
    loading: false,
    emptyText: "暂无可展示的数据",
    height: 260,
  },
);

const host = ref<HTMLDivElement | null>(null);
let instance: ChartInstance | null = null;
let observer: ResizeObserver | null = null;

function dispose() {
  observer?.disconnect();
  observer = null;
  instance?.dispose();
  instance = null;
}

function draw() {
  if (props.loading || props.option === null || host.value === null) return;

  if (instance === null) {
    instance = echarts.init(host.value, undefined, { renderer: "svg" });
    if (typeof ResizeObserver !== "undefined") {
      observer = new ResizeObserver(() => instance?.resize());
      observer.observe(host.value);
    }
  }
  instance.setOption(props.option, true);
}

watch(
  () => [props.option, props.loading] as const,
  () => {
    void nextTick(() => {
      if (props.loading || props.option === null) {
        dispose();
        return;
      }
      draw();
    });
  },
);

onMounted(() => {
  void nextTick(draw);
});

onBeforeUnmount(dispose);
</script>

<template>
  <figure class="chart-frame" data-testid="chart-frame">
    <figcaption v-if="title" class="chart-frame__title">{{ title }}</figcaption>
    <p v-if="hint" class="chart-frame__hint">{{ hint }}</p>

    <div v-if="loading" class="chart-frame__loading" data-testid="chart-loading" role="status">
      <div class="chart-frame__bars" aria-hidden="true">
        <span v-for="bar in 5" :key="bar" :style="{ height: `${28 + bar * 14}px` }"></span>
      </div>
      <p class="chart-frame__loading-text">图表加载中…</p>
    </div>

    <p v-else-if="option === null" class="chart-frame__empty" data-testid="chart-empty">
      {{ emptyText }}
    </p>

    <div
      v-else
      ref="host"
      class="chart-frame__canvas"
      data-testid="chart-canvas"
      role="img"
      :aria-label="title || '图表'"
      :style="{ height: `${height}px` }"
    ></div>
  </figure>
</template>

<style scoped>
.chart-frame {
  margin: 0;
  padding: 1rem;
  border: 1px solid #e6e8eb;
  border-radius: 8px;
}

.chart-frame__title {
  margin-bottom: 0.25rem;
  color: #1f2937;
  font-size: 0.95rem;
  font-weight: 600;
}

.chart-frame__hint {
  margin: 0 0 0.5rem;
  color: #6b7280;
  font-size: 0.85rem;
}

.chart-frame__canvas {
  width: 100%;
}

.chart-frame__empty {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 140px;
  margin: 0;
  padding: 1rem;
  border: 1px dashed #d5d9e0;
  border-radius: 8px;
  background: #fafbfc;
  color: #6b7280;
  text-align: center;
}

.chart-frame__loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.75rem;
  min-height: 180px;
  border-radius: 8px;
  background: #fafbfc;
}

.chart-frame__bars {
  display: flex;
  align-items: flex-end;
  gap: 0.5rem;
  height: 108px;
}

.chart-frame__bars span {
  width: 22px;
  border-radius: 4px;
  background: #e6e9ef;
  animation: chart-frame-pulse 1.2s ease-in-out infinite;
}

.chart-frame__bars span:nth-child(2) {
  animation-delay: 0.12s;
}

.chart-frame__bars span:nth-child(3) {
  animation-delay: 0.24s;
}

.chart-frame__bars span:nth-child(4) {
  animation-delay: 0.36s;
}

.chart-frame__bars span:nth-child(5) {
  animation-delay: 0.48s;
}

.chart-frame__loading-text {
  margin: 0;
  color: #9aa2ae;
  font-size: 0.85rem;
}

@keyframes chart-frame-pulse {
  0%,
  100% {
    opacity: 0.45;
  }
  50% {
    opacity: 1;
  }
}
</style>
