// 色板不靠肉眼挑：这里逐项校验色值的可测属性。
// 上一版项目把配色单色化之后，图表的系列之间分辨不出来，只能返工重调，
// 所以这些数字是硬门槛——改色值前先跑这个测试。
//
// 亮色改造后门槛拆成两条：填充要够艳（饱和度），边界要够重（描边对底色 3:1）。
// 「填充自己对白底 ≥3:1」这条不再成立，也不该再拿它当门槛——亮与可辨由一对色共同满足。

import { describe, expect, it } from "vitest";
import { contrastRatio, hslSaturation, hueDegrees, hueDistance, relativeLuminance } from "./color";
import {
  CATEGORICAL_OUTLINE_PALETTE,
  CATEGORICAL_PALETTE,
  CHART_EDGE_COLOR,
  CHART_LABEL_COLOR,
  CHART_MUTED_LABEL_COLOR,
  CHART_SPLIT_LINE_COLOR,
  CHART_SURFACE_COLOR,
  MIN_LABEL_CONTRAST_RATIO,
  MIN_PALETTE_HUE_SPREAD_DEGREES,
  MIN_SERIES_CONTRAST_RATIO,
  MIN_SERIES_HUE_DISTANCE_DEGREES,
  MIN_SERIES_SATURATION,
  UI_PRIMARY_COLOR,
  categoricalColorAt,
  categoricalOutlineColorAt,
  minSeriesHueDistanceDegrees,
  minSeriesOutlineContrastRatio,
  minSeriesSaturation,
  paletteHueSpreadDegrees,
} from "./palette";

describe("分类色板", () => {
  it("填充够艳：每个系列色都是高饱和，不发灰", () => {
    for (const color of CATEGORICAL_PALETTE) {
      expect(hslSaturation(color)).toBeGreaterThanOrEqual(MIN_SERIES_SATURATION);
    }
    expect(minSeriesSaturation()).toBeGreaterThanOrEqual(MIN_SERIES_SATURATION);
  });

  it("亮色填充不负责边界，但描边必须顶住：每个描边色对底色达到非文本对比度要求", () => {
    for (const color of CATEGORICAL_OUTLINE_PALETTE) {
      expect(contrastRatio(color, CHART_SURFACE_COLOR)).toBeGreaterThanOrEqual(
        MIN_SERIES_CONTRAST_RATIO,
      );
    }
    expect(minSeriesOutlineContrastRatio()).toBeGreaterThanOrEqual(MIN_SERIES_CONTRAST_RATIO);
  });

  it("描边与填充一一配对：同色相的深色，看着是「这块的边」而不是套了别人的圈", () => {
    expect(CATEGORICAL_OUTLINE_PALETTE).toHaveLength(CATEGORICAL_PALETTE.length);
    CATEGORICAL_PALETTE.forEach((fill, index) => {
      const outline = categoricalOutlineColorAt(index);
      expect(outline).toBe(CATEGORICAL_OUTLINE_PALETTE[index]);
      expect(hueDistance(hueDegrees(outline), hueDegrees(fill))).toBeLessThanOrEqual(20);
      expect(relativeLuminance(outline)).toBeLessThan(relativeLuminance(fill));
    });
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

  it("系列数超出色板长度时填充与描边同循环，且仍取自同一套色板", () => {
    const size = CATEGORICAL_PALETTE.length;
    expect(categoricalColorAt(0)).toBe(CATEGORICAL_PALETTE[0]);
    expect(categoricalColorAt(size)).toBe(CATEGORICAL_PALETTE[0]);
    expect(categoricalOutlineColorAt(size)).toBe(CATEGORICAL_OUTLINE_PALETTE[0]);
    expect(categoricalColorAt(size + 2)).toBe(CATEGORICAL_PALETTE[2]);
    expect(categoricalOutlineColorAt(size + 2)).toBe(CATEGORICAL_OUTLINE_PALETTE[2]);
    expect(CATEGORICAL_PALETTE).toContain(categoricalColorAt(99));
  });
});

describe("关系图连线色", () => {
  it("连线的信息就在线本身，对底色达到非文本对比度要求", () => {
    expect(contrastRatio(CHART_EDGE_COLOR, CHART_SURFACE_COLOR)).toBeGreaterThanOrEqual(
      MIN_SERIES_CONTRAST_RATIO,
    );
  });

  it("比网格分隔线重：连线不许复用那条「故意画得看不见」的线", () => {
    // 曾经的缺陷：关系图连线直接取 CHART_SPLIT_LINE_COLOR，与白底几乎同色，连线看不出。
    const edgeContrast = contrastRatio(CHART_EDGE_COLOR, CHART_SURFACE_COLOR);
    const splitLineContrast = contrastRatio(CHART_SPLIT_LINE_COLOR, CHART_SURFACE_COLOR);
    expect(CHART_EDGE_COLOR).not.toBe(CHART_SPLIT_LINE_COLOR);
    expect(edgeContrast).toBeGreaterThan(splitLineContrast * 2);
  });
});
