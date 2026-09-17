// KPI 卡的着色契约：accent 只收语义枚举名，不收裸色值——
// 六个名字在组件内部一一映射到主题令牌，调用方没有任何直接指定颜色的入口。

export const STAT_CARD_ACCENTS = ["primary", "up", "down", "success", "warning", "danger"] as const;

export type StatCardAccent = (typeof STAT_CARD_ACCENTS)[number];

/** 趋势只描述方向与文案；着色由组件按方向决定，调用方不传颜色。 */
export interface StatCardTrend {
  direction: "up" | "down";
  label: string;
}
