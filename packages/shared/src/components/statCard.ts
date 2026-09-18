// KPI 卡自己的契约。着色枚举（Accent）与 MeterBar 共用，定义在 ./accent。

/** 趋势只描述方向与文案；着色由组件按方向决定，调用方不传颜色。 */
export interface StatCardTrend {
  direction: "up" | "down";
  label: string;
}
