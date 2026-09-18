// 图形构造：把「类别 + 数值」映射成 ECharts 配置。
//
// 这里只有形状的取舍（饼图表达部分与整体、横向条形便于沿同一基线比较长度），
// 没有任何业务含义——类别叫什么、按什么顺序来，由调用方决定并原样保留。

import type { BarSeriesOption, GraphSeriesOption, PieSeriesOption } from "echarts/charts";
import type {
  GridComponentOption,
  LegendComponentOption,
  TooltipComponentOption,
} from "echarts/components";
import type { ComposeOption } from "echarts/core";
import {
  CATEGORICAL_PALETTE,
  CHART_EDGE_COLOR,
  CHART_LABEL_COLOR,
  CHART_MARK_BORDER_COLOR,
  CHART_MUTED_LABEL_COLOR,
  CHART_SPLIT_LINE_COLOR,
  categoricalColorAt,
  categoricalOutlineColorAt,
} from "./palette";

export type ChartOption = ComposeOption<
  | BarSeriesOption
  | PieSeriesOption
  | GraphSeriesOption
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
 * 扇区填充分类色板的亮色，描边取同色相的深色——描边兼作扇区之间的分隔，
 * 亮色底上再压白色缝会看不出边界。
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
        itemStyle: { borderWidth: 2 },
        label: { color: CHART_LABEL_COLOR, fontSize: 12, formatter: "{b} {d}%" },
        labelLine: { length: 8, length2: 8 },
        data: data.map((item, index) => ({
          name: item.name,
          value: item.value,
          itemStyle: { borderColor: categoricalOutlineColorAt(index) },
        })),
      },
    ],
  };
}

export type NamedSeries = { name: string; data: readonly CategoryValue[] };

type ComparisonDatum = {
  name: string;
  value: number;
  diff: number;
  itemStyle: { color: string; borderColor: string; borderWidth: number };
};

/**
 * 成对横向条形：两组系列沿同一类别轴、同一基线并排，用于直读两组数值的差值。
 * 两组饼图之间人眼无法比较扇区大小，这张图存在正是为了解决这个问题——
 * 因此第二组会在条形末端显式标出与第一组的差值，不指望读者自己去比两根条的长度。
 *
 * 两组的类别顺序由调用方保证一致，这里按第一组的顺序取类别轴，不做校验、不重排。
 */
export function toComparisonBarOption(series: readonly [NamedSeries, NamedSeries]): ChartOption | null {
  const [first, second] = series;
  if (!hasDrawableValues(first.data) && !hasDrawableValues(second.data)) return null;

  const categories = first.data.map((item) => item.name);
  const baselineValues = first.data.map((item) => item.value);

  // 两组系列各占色板的一个下标，填充与描边都跟着系列走，不跟着类别走。
  const toDatum = (item: CategoryValue, index: number, paletteIndex: number): ComparisonDatum => ({
    name: item.name,
    value: item.value,
    diff: item.value - (baselineValues[index] ?? 0),
    itemStyle: {
      color: categoricalColorAt(paletteIndex),
      borderColor: categoricalOutlineColorAt(paletteIndex),
      borderWidth: 1,
    },
  });

  return {
    grid: { left: 4, right: 56, top: 8, bottom: 28, containLabel: true },
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
    legend: {
      bottom: 0,
      icon: "circle",
      itemWidth: 10,
      itemHeight: 10,
      itemGap: 16,
      textStyle: { color: CHART_LABEL_COLOR, fontSize: 12 },
    },
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
      data: categories,
      axisTick: { show: false },
      axisLine: { show: false },
      axisLabel: { color: CHART_LABEL_COLOR, fontSize: 12 },
    },
    series: [
      {
        name: first.name,
        type: "bar",
        barMaxWidth: 18,
        itemStyle: { borderRadius: [0, 4, 4, 0] },
        data: first.data.map((item, index) => toDatum(item, index, 0)),
      },
      {
        name: second.name,
        type: "bar",
        barMaxWidth: 18,
        itemStyle: { borderRadius: [0, 4, 4, 0] },
        label: {
          show: true,
          position: "right",
          color: CHART_MUTED_LABEL_COLOR,
          fontSize: 12,
          formatter: (params) => {
            const datum = params.data as ComparisonDatum;
            if (datum.diff === 0) return `${datum.value}`;
            const sign = datum.diff > 0 ? "+" : "";
            return `${datum.value}（${sign}${datum.diff}）`;
          },
        },
        data: second.data.map((item, index) => toDatum(item, index, 1)),
      },
    ],
  };
}

export type GraphNodeDatum = { id: string; name: string; category: number; marked?: boolean };
export type GraphEdgeDatum = { source: string; target: string };
export type GraphCategoryDatum = { name: string };

/**
 * 力导向关系图：节点数量与连线在运行前不固定，用它铺开一张网络而不预设坐标。
 * 类别顺序决定取色顺序，供调用方区分不同种类的节点；节点用高饱和亮色填充，
 * 轮廓另取同色相的深描边（亮色与 3:1 的边界要求各由一半承担），
 * `marked` 的节点则改用它自己的强调色描边并加粗，供调用方标出需要着重提示的数据点，
 * 标记的判断本身不在这里做。
 *
 * 没有连线的图看不出关系，和没有节点一样视为没有可画的东西。
 */
export function toGraphOption(
  nodes: readonly GraphNodeDatum[],
  edges: readonly GraphEdgeDatum[],
  categories: readonly GraphCategoryDatum[],
): ChartOption | null {
  if (nodes.length === 0 || edges.length === 0) return null;

  return {
    tooltip: { trigger: "item" },
    legend: [
      {
        data: categories.map((category) => category.name),
        bottom: 0,
        icon: "circle",
        itemWidth: 10,
        itemHeight: 10,
        itemGap: 16,
        textStyle: { color: CHART_LABEL_COLOR, fontSize: 12 },
      },
    ],
    series: [
      {
        type: "graph",
        layout: "force",
        roam: true,
        draggable: true,
        label: { show: true, position: "right", color: CHART_LABEL_COLOR, fontSize: 12 },
        lineStyle: { color: CHART_EDGE_COLOR, width: 1.2, curveness: 0.1 },
        force: { repulsion: 140, edgeLength: 80 },
        categories: categories.map((category, index) => ({
          name: category.name,
          itemStyle: { color: categoricalColorAt(index) },
        })),
        data: nodes.map((node) => ({
          id: node.id,
          name: node.name,
          category: node.category,
          symbolSize: node.marked ? 42 : 30,
          itemStyle: {
            color: categoricalColorAt(node.category),
            borderColor: node.marked
              ? CHART_MARK_BORDER_COLOR
              : categoricalOutlineColorAt(node.category),
            borderWidth: node.marked ? 3 : 2,
          },
        })),
        links: edges.map((edge) => ({ source: edge.source, target: edge.target })),
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
          itemStyle: {
            color: categoricalColorAt(index),
            borderColor: categoricalOutlineColorAt(index),
            borderWidth: 1,
          },
        })),
      },
    ],
  };
}
