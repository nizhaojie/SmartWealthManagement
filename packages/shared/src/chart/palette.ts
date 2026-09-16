// 主题令牌：UI 主色与分类色板是两个东西，分开定义。
//
// UI 主色是单一色相，服务于界面自身的强调（按钮、链接、选中态）——整套界面
// 共用一种色相正是它要的效果。
// 分类色板服务于图表中彼此并列的系列，需要色相拉开，系列之间才分辨得出来。
// 把主色的同色系深浅拿来当色板，图表就会退化成单色，系列失去辨识度。

import { contrastRatio, hueDegrees, hueDistance } from "./color";

/** 界面自身的主色，单一色相，不参与图表配色。 */
export const UI_PRIMARY_COLOR = "#1F6FEB";

/** 图表的绘制底色，是可读性校验的基准面。 */
export const CHART_SURFACE_COLOR = "#FFFFFF";

/** 坐标轴与数值标签的中性色，按正文级别要求对比度。 */
export const CHART_LABEL_COLOR = "#374151";

/** 次要说明文字的中性色。 */
export const CHART_MUTED_LABEL_COLOR = "#6B7280";

/** 网格分隔线的中性色。 */
export const CHART_SPLIT_LINE_COLOR = "#EEF0F3";

/** 文字类元素对底色要求的最低对比度（WCAG 正文级）。 */
export const MIN_LABEL_CONTRAST_RATIO = 4.5;

/**
 * 分类色板。六个色相均匀铺开，每个色相对底色都有 3:1 以上的对比度
 * （WCAG 对非文本图形元素的要求），相邻色相的夹角不小于 25 度。
 * 这些数值由 `palette.test.ts` 逐项校验，改动色值前先跑它，不要凭眼睛挑。
 */
export const CATEGORICAL_PALETTE = [
  "#CE7A22",
  "#7C9040",
  "#2E9E6B",
  "#2F6FB0",
  "#7A5FC7",
  "#B2477E",
] as const;

/** 标记态强调色：图表里需要着重标出的数据点用它描边，和分类色板独立，不参与类别轮转。 */
export const CHART_MARK_BORDER_COLOR = "#B3261E";

/** 系列色相对底色的最低对比度（WCAG 非文本对比度）。 */
export const MIN_SERIES_CONTRAST_RATIO = 3;

/** 任意两个系列色相之间的最小夹角。 */
export const MIN_SERIES_HUE_DISTANCE_DEGREES = 25;

/** 分类色板覆盖的最小色相跨度。 */
export const MIN_PALETTE_HUE_SPREAD_DEGREES = 200;

/** 按系列下标取色，超出色板长度后循环。 */
export function categoricalColorAt(index: number): string {
  const size = CATEGORICAL_PALETTE.length;
  return CATEGORICAL_PALETTE[((index % size) + size) % size];
}

/**
 * 色板覆盖的色相跨度：能同时框住全部色相的那段最短圆弧的角度。
 * 单色化改造会让这个值塌到接近 0。
 */
export function paletteHueSpreadDegrees(): number {
  const hues = CATEGORICAL_PALETTE.map(hueDegrees).sort((first, second) => first - second);
  let widestGap = hues.length > 0 ? 360 - hues[hues.length - 1] + hues[0] : 360;
  for (let index = 1; index < hues.length; index += 1) {
    widestGap = Math.max(widestGap, hues[index] - hues[index - 1]);
  }
  return 360 - widestGap;
}

/** 系列色对底色的最低对比度，低于 1 说明色板退化成了单色。 */
export function minSeriesContrastRatio(): number {
  return Math.min(
    ...CATEGORICAL_PALETTE.map((color) => contrastRatio(color, CHART_SURFACE_COLOR)),
  );
}

/** 色板中两两色相的最小夹角，夹角过小意味着两个系列看起来是同一个颜色。 */
export function minSeriesHueDistanceDegrees(): number {
  const hues = CATEGORICAL_PALETTE.map(hueDegrees);
  let minimum = 180;
  for (const first of hues) {
    for (const second of hues) {
      if (first === second) continue;
      minimum = Math.min(minimum, hueDistance(first, second));
    }
  }
  return minimum;
}
