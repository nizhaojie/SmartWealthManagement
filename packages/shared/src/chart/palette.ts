// 主题令牌：UI 主色与分类色板是两个东西，分开定义。
//
// UI 主色是单一色相，服务于界面自身的强调（按钮、链接、选中态）——整套界面
// 共用一种色相正是它要的效果。
// 分类色板服务于图表中彼此并列的系列，需要色相拉开，系列之间才分辨得出来。
// 把主色的同色系深浅拿来当色板，图表就会退化成单色，系列失去辨识度。
//
// 色板是一套，不分图表：所有图表共用 CATEGORICAL_PALETTE 取色。
// 每个色配一条同色相的深描边 CATEGORICAL_OUTLINE_PALETTE——高饱和亮色在白底上
// 对不出 3:1（橙 2.4、青 2.1、绿 1.7），所以「亮得起来」与「看得出边界」拆开承担：
// 填充负责艳，描边负责把边界从白底里拎出来，描边对底色按 WCAG 非文本对比度 3:1 把关。

import { contrastRatio, hslSaturation, hueDegrees, hueDistance } from "./color";

/** 界面自身的主色，单一色相，不参与图表配色。 */
export const UI_PRIMARY_COLOR = "#1F6FEB";

/** 图表的绘制底色，是可读性校验的基准面。 */
export const CHART_SURFACE_COLOR = "#FFFFFF";

/** 坐标轴与数值标签的中性色，按正文级别要求对比度。 */
export const CHART_LABEL_COLOR = "#374151";

/** 次要说明文字的中性色。 */
export const CHART_MUTED_LABEL_COLOR = "#6B7280";

/** 网格分隔线的中性色。它只是辅助读数的背景线，对底色刻意做得很淡，不能拿它画承载信息的线。 */
export const CHART_SPLIT_LINE_COLOR = "#EEF0F3";

/**
 * 关系图连线的中性色。连线本身就是「谁和谁有关」这条信息，没有它图就散了，
 * 因此按 WCAG 非文本图形元素要求压到对底色 3:1 以上——比网格分隔线重一个档，
 * 又比正文标签轻，不至于盖过节点文字。
 */
export const CHART_EDGE_COLOR = "#7B8494";

/** 文字类元素对底色要求的最低对比度（WCAG 正文级）。 */
export const MIN_LABEL_CONTRAST_RATIO = 4.5;

/**
 * 分类色板：高饱和亮色，按系列序取色，超出长度后循环。
 *
 * 六个性相均匀铺开，填充一律压在高饱和一侧——亮色在小尺寸标记上比深色更抓眼，
 * 但都不足以自己顶住 3:1，所以每个色都配一条同色相的深描边（见下）。
 * 这些数值由 `palette.test.ts` 逐项校验，改动色值前先跑它，不要凭眼睛挑。
 */
export const CATEGORICAL_PALETTE = [
  "#FF3B6B",
  "#FF8A00",
  "#00C2FF",
  "#7C3AED",
  "#00E676",
  "#D946EF",
] as const;

/** 系列描边：与填充同色相压深到对底色 3:1 以上，负责把亮色标记的边界从白底里拎出来。 */
export const CATEGORICAL_OUTLINE_PALETTE = [
  "#E50038",
  "#BC6600",
  "#0085AF",
  "#6315E8",
  "#008F49",
  "#C113DC",
] as const;

/** 标记态强调色：图表里需要着重标出的数据点用它描边，和分类色板独立，不参与类别轮转。 */
export const CHART_MARK_BORDER_COLOR = "#B3261E";

/** 系列填充色的最低 HSL 饱和度。低于它的色已经不是「艳」而是发灰，白底上看着像没上色。 */
export const MIN_SERIES_SATURATION = 0.75;

/** 系列描边对底色的最低对比度（WCAG 非文本对比度）。连线与标记态描边共用这条线。 */
export const MIN_SERIES_CONTRAST_RATIO = 3;

/** 任意两个系列色相之间的最小夹角。 */
export const MIN_SERIES_HUE_DISTANCE_DEGREES = 25;

/** 分类色板覆盖的最小色相跨度。 */
export const MIN_PALETTE_HUE_SPREAD_DEGREES = 200;

/** 按系列下标取填充色，超出色板长度后循环。 */
export function categoricalColorAt(index: number): string {
  return cycleAt(CATEGORICAL_PALETTE, index);
}

/** 按系列下标取描边色，与 `categoricalColorAt` 同一套下标，两者始终配对。 */
export function categoricalOutlineColorAt(index: number): string {
  return cycleAt(CATEGORICAL_OUTLINE_PALETTE, index);
}

/** 色板覆盖的色相跨度：能同时框住全部色相的那段最短圆弧的角度。 */
export function paletteHueSpreadDegrees(): number {
  return hueSpreadDegrees(CATEGORICAL_PALETTE);
}

/** 填充色中最小的 HSL 饱和度，低于 `MIN_SERIES_SATURATION` 说明色板褪成了灰。 */
export function minSeriesSaturation(): number {
  return Math.min(...CATEGORICAL_PALETTE.map(hslSaturation));
}

/** 系列描边对底色的最低对比度，低于 3 说明亮色标记的边界又要糊回白底。 */
export function minSeriesOutlineContrastRatio(): number {
  return Math.min(
    ...CATEGORICAL_OUTLINE_PALETTE.map((color) => contrastRatio(color, CHART_SURFACE_COLOR)),
  );
}

/** 色板中两两色相的最小夹角，夹角过小意味着两个系列看起来是同一个颜色。 */
export function minSeriesHueDistanceDegrees(): number {
  return minHueDistanceDegrees(CATEGORICAL_PALETTE);
}

function cycleAt(colors: readonly string[], index: number): string {
  const size = colors.length;
  return colors[((index % size) + size) % size];
}

function hueSpreadDegrees(colors: readonly string[]): number {
  const hues = colors.map(hueDegrees).sort((first, second) => first - second);
  let widestGap = hues.length > 0 ? 360 - hues[hues.length - 1] + hues[0] : 360;
  for (let index = 1; index < hues.length; index += 1) {
    widestGap = Math.max(widestGap, hues[index] - hues[index - 1]);
  }
  return 360 - widestGap;
}

function minHueDistanceDegrees(colors: readonly string[]): number {
  const hues = colors.map(hueDegrees);
  let minimum = 180;
  for (const first of hues) {
    for (const second of hues) {
      if (first === second) continue;
      minimum = Math.min(minimum, hueDistance(first, second));
    }
  }
  return minimum;
}
