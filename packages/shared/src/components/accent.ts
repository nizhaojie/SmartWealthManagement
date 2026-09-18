// 展示件的着色契约：accent 只收语义枚举名，不收裸色值——
// 六个名字在组件内部一一映射到主题令牌，调用方没有任何直接指定颜色的入口。
// StatCard（KPI 色条）与 MeterBar（进度条填充）共用这一份清单。

export const ACCENTS = ["primary", "up", "down", "success", "warning", "danger"] as const;

export type Accent = (typeof ACCENTS)[number];
