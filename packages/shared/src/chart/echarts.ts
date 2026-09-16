// ECharts 的按需注册集中在这一处，图表壳与图形构造都从这里取实例。
// 用 core 而不是整包：客户端的 bundle 里只应有饼图、条形图与 SVG 渲染器。

import { BarChart, GraphChart, PieChart } from "echarts/charts";
import { GridComponent, LegendComponent, TooltipComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { SVGRenderer } from "echarts/renderers";

echarts.use([
  BarChart,
  PieChart,
  GraphChart,
  GridComponent,
  LegendComponent,
  TooltipComponent,
  SVGRenderer,
]);

export { echarts };
export type ChartInstance = ReturnType<typeof echarts.init>;
