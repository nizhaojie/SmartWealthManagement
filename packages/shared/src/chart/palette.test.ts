// 色板不靠肉眼挑：这里逐项校验色值的可测属性。
// 上一版项目把配色单色化之后，图表的系列之间分辨不出来，只能返工重调，
// 所以这些数字是硬门槛——改色值前先跑这个测试。

import { describe, expect, it } from "vitest";
import { contrastRatio, hueDegrees, hueDistance } from "./color";
import {
  CATEGORICAL_PALETTE,
  CHART_LABEL_COLOR,
  CHART_MUTED_LABEL_COLOR,
  CHART_SURFACE_COLOR,
  MIN_LABEL_CONTRAST_RATIO,
  MIN_PALETTE_HUE_SPREAD_DEGREES,
  MIN_SERIES_CONTRAST_RATIO,
  MIN_SERIES_HUE_DISTANCE_DEGREES,
  UI_PRIMARY_COLOR,
  categoricalColorAt,
  minSeriesContrastRatio,
  minSeriesHueDistanceDegrees,
  paletteHueSpreadDegrees,
} from "./palette";

describe("分类色板", () => {
  it("每个系列色对底色都达到 WCAG 非文本对比度要求", () => {
    for (const color of CATEGORICAL_PALETTE) {
      expect(contrastRatio(color, CHART_SURFACE_COLOR)).toBeGreaterThanOrEqual(
        MIN_SERIES_CONTRAST_RATIO,
      );
    }
    expect(minSeriesContrastRatio()).toBeGreaterThanOrEqual(MIN_SERIES_CONTRAST_RATIO);
  });

  it("任意两个系列色的色相都拉得开，不会看着像同一个颜色", () => {
    const hues = CATEGORICAL_PALETTE.map(hueDegrees);
    for (const first of hues) {
      for (const second of hues) {
        if (first === second) continue;
        expect(hueDistance(first, second)).toBeGreaterThanOrEqual(
          MIN_SERIES_HUE_DISTANCE_DEGREES,
        );
      }
    }
    expect(minSeriesHueDistanceDegrees()).toBeGreaterThanOrEqual(
      MIN_SERIES_HUE_DISTANCE_DEGREES,
    );
  });

  it("整块色板铺开足够的色相跨度，而不是同一色相的深浅变化", () => {
    expect(paletteHueSpreadDegrees()).toBeGreaterThanOrEqual(MIN_PALETTE_HUE_SPREAD_DEGREES);
  });

  it("分类色板不是 UI 主色的深浅变化：主色色相近旁最多只有一个系列色", () => {
    // 单色化改造的特征就是整块色板塌进主色的色相里，那时这里的计数会等于色板长度。
    const primaryHue = hueDegrees(UI_PRIMARY_COLOR);
    const nearPrimary = CATEGORICAL_PALETTE.filter(
      (color) => hueDistance(hueDegrees(color), primaryHue) <= 30,
    );

    expect(nearPrimary.length).toBeLessThanOrEqual(1);
    expect(CATEGORICAL_PALETTE).not.toContain(UI_PRIMARY_COLOR);
  });

  it("文字与标签用的中性色达到正文级对比度", () => {
    for (const color of [CHART_LABEL_COLOR, CHART_MUTED_LABEL_COLOR]) {
      expect(contrastRatio(color, CHART_SURFACE_COLOR)).toBeGreaterThanOrEqual(
        MIN_LABEL_CONTRAST_RATIO,
      );
    }
  });

  it("系列数超出色板长度时循环取色，且仍取自同一套色板", () => {
    expect(categoricalColorAt(0)).toBe(CATEGORICAL_PALETTE[0]);
    expect(categoricalColorAt(CATEGORICAL_PALETTE.length)).toBe(CATEGORICAL_PALETTE[0]);
    expect(categoricalColorAt(CATEGORICAL_PALETTE.length + 2)).toBe(CATEGORICAL_PALETTE[2]);
    expect(CATEGORICAL_PALETTE).toContain(categoricalColorAt(99));
  });
});
