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

const emit = defineEmits<{
  elementClick: [params: unknown];
}>();

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
    instance.on("click", (params) => emit("elementClick", params));
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
/* 着色与间距一律经 --wm-* 令牌（tokenDiscipline.test.ts 有裸色值闸门），行为与结构保持原样；
   容器样式并入 02 的卡片语言（白面 + 发丝线 + 圆角 + 卡片阴影）。
   1px 描边与骨架条的 22px / 108px 尺寸不在令牌刻度内，属令牌纪律声明的极少数例外。 */
.chart-frame {
  margin: 0;
  padding: var(--wm-space-4);
  border: 1px solid var(--wm-border);
  border-radius: var(--wm-radius-md);
  background-color: var(--wm-bg-card);
  box-shadow: var(--wm-shadow-card);
}

.chart-frame__title {
  margin-bottom: var(--wm-space-1);
  color: var(--wm-text-primary);
  font-size: 0.95rem;
  font-weight: 600;
}

.chart-frame__hint {
  margin: 0 0 var(--wm-space-2);
  color: var(--wm-text-muted);
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
  padding: var(--wm-space-4);
  border: 1px dashed var(--wm-border);
  border-radius: var(--wm-radius-md);
  background: var(--wm-bg-page);
  color: var(--wm-text-muted);
  text-align: center;
}

.chart-frame__loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--wm-space-3);
  min-height: 180px;
  border-radius: var(--wm-radius-md);
  background: var(--wm-bg-page);
}

.chart-frame__bars {
  display: flex;
  align-items: flex-end;
  gap: var(--wm-space-2);
  height: 108px;
}

.chart-frame__bars span {
  width: 22px;
  border-radius: var(--wm-radius-sm);
  background: var(--wm-border);
}

.chart-frame__loading-text {
  margin: 0;
  color: var(--wm-text-muted);
  font-size: 0.85rem;
}

/* 骨架条的呼吸只在系统未要求减少动效时启用；不做逐项 nth-child 错峰延迟 */
@media (prefers-reduced-motion: no-preference) {
  @keyframes chart-frame-pulse {
    0%,
    100% {
      opacity: 0.45;
    }
    50% {
      opacity: 1;
    }
  }

  .chart-frame__bars span {
    animation: chart-frame-pulse 1.2s ease-in-out infinite;
  }
}
</style>
