// 图形构造：把「类别 + 数值」映射成 ECharts 配置。
//
// 这里只有形状的取舍（饼图表达部分与整体、横向条形便于沿同一基线比较长度），
// 没有任何业务含义——类别叫什么、按什么顺序来，由调用方决定并原样保留。

import type { BarSeriesOption, PieSeriesOption } from "echarts/charts";
import type {
  GridComponentOption,
  LegendComponentOption,
  TooltipComponentOption,
} from "echarts/components";
import type { ComposeOption } from "echarts/core";
import {
  CATEGORICAL_PALETTE,
  CHART_LABEL_COLOR,
  CHART_MUTED_LABEL_COLOR,
  CHART_SPLIT_LINE_COLOR,
  CHART_SURFACE_COLOR,
  categoricalColorAt,
} from "./palette";

export type ChartOption = ComposeOption<
  | BarSeriesOption
  | PieSeriesOption
  | GridComponentOption
  | LegendComponentOption
  | TooltipComponentOption
>;

export type CategoryValue = { name: string; value: number };

function hasDrawableValues(data: readonly CategoryValue[]): boolean {
  return data.some((item) => item.value > 0);
}

/**
 * 环图：类别少、只读占比时用它。
 * 返回 null 表示没有可画的东西，调用方应改渲染空状态，而不是画一个空图。
 */
export function toDonutOption(data: readonly CategoryValue[]): ChartOption | null {
  if (!hasDrawableValues(data)) return null;

  return {
    color: [...CATEGORICAL_PALETTE],
    tooltip: { trigger: "item", formatter: "{b}：{c}（{d}%）" },
    legend: {
      bottom: 0,
      icon: "circle",
      itemWidth: 10,
      itemHeight: 10,
      itemGap: 16,
      textStyle: { color: CHART_LABEL_COLOR, fontSize: 12 },
    },
    series: [
      {
        type: "pie",
        radius: ["52%", "76%"],
        center: ["50%", "44%"],
        minAngle: 2,
        avoidLabelOverlap: true,
        itemStyle: { borderColor: CHART_SURFACE_COLOR, borderWidth: 2 },
        label: { color: CHART_LABEL_COLOR, fontSize: 12, formatter: "{b} {d}%" },
        labelLine: { length: 8, length2: 8 },
        data: data.map((item) => ({ name: item.name, value: item.value })),
      },
    ],
  };
}

/**
 * 横向条形图：有序类别沿同一基线比较长度用它。
 * 类别顺序由传入顺序决定，不按数值重排。
 */
export function toBarOption(data: readonly CategoryValue[]): ChartOption | null {
  if (!hasDrawableValues(data)) return null;

  return {
    grid: { left: 4, right: 40, top: 8, bottom: 4, containLabel: true },
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
    xAxis: {
      type: "value",
      axisLabel: { color: CHART_MUTED_LABEL_COLOR, fontSize: 12 },
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: { lineStyle: { color: CHART_SPLIT_LINE_COLOR } },
    },
    yAxis: {
      type: "category",
      // 类别轴默认自下而上排布，取反后传入的第一个类别落在顶部。
      inverse: true,
      data: data.map((item) => item.name),
      axisTick: { show: false },
      axisLine: { show: false },
      axisLabel: { color: CHART_LABEL_COLOR, fontSize: 12 },
    },
    series: [
      {
        type: "bar",
        barMaxWidth: 22,
        itemStyle: { borderRadius: [0, 4, 4, 0] },
        label: { show: true, position: "right", color: CHART_MUTED_LABEL_COLOR, fontSize: 12 },
        data: data.map((item, index) => ({
          name: item.name,
          value: item.value,
          itemStyle: { color: categoricalColorAt(index) },
        })),
      },
    ],
  };
}
