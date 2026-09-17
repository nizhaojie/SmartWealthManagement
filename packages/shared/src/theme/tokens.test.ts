// 令牌的可用性不靠肉眼挑：文本类与涨跌色必须对白底达到 WCAG 正文级对比度。
// 与 chart/palette.test.ts 同一套门槛——改色值前先跑这个测试。

import { describe, expect, it } from "vitest";
import { contrastRatio } from "../chart/color";
import tokensCssSource from "./tokens.css?raw";
import { MIN_TEXT_CONTRAST_RATIO, THEME_COLORS } from "./tokens";

const WHITE_SURFACE = "#FFFFFF";

/** 每个色彩令牌在 tokens.css 里对应的自定义属性名。 */
const CSS_VARIABLE_BY_TOKEN: Record<keyof typeof THEME_COLORS, string> = {
  primary: "--wm-color-primary",
  up: "--wm-color-up",
  down: "--wm-color-down",
  success: "--wm-color-success",
  warning: "--wm-color-warning",
  danger: "--wm-color-danger",
  textPrimary: "--wm-text-primary",
  textSecondary: "--wm-text-secondary",
  textMuted: "--wm-text-muted",
  textPlaceholder: "--wm-text-placeholder",
  pageBackground: "--wm-bg-page",
  cardSurface: "--wm-bg-card",
  border: "--wm-border",
  hairline: "--wm-border-hairline",
};

describe("主题令牌对比度", () => {
  it("文本与强调类令牌对白底达到 WCAG 正文级对比度", () => {
    const textTokens = [
      THEME_COLORS.primary,
      THEME_COLORS.textPrimary,
      THEME_COLORS.textSecondary,
      THEME_COLORS.textMuted,
    ] as const;

    for (const color of textTokens) {
      expect(contrastRatio(color, WHITE_SURFACE)).toBeGreaterThanOrEqual(
        MIN_TEXT_CONTRAST_RATIO,
      );
    }
  });

  it("涨跌色对白底达到 WCAG 正文级对比度（红涨绿跌）", () => {
    for (const color of [THEME_COLORS.up, THEME_COLORS.down]) {
      expect(contrastRatio(color, WHITE_SURFACE)).toBeGreaterThanOrEqual(
        MIN_TEXT_CONTRAST_RATIO,
      );
    }
  });

  it("语义状态色对白底达到 WCAG 正文级对比度", () => {
    for (const color of [THEME_COLORS.success, THEME_COLORS.warning, THEME_COLORS.danger]) {
      expect(contrastRatio(color, WHITE_SURFACE)).toBeGreaterThanOrEqual(
        MIN_TEXT_CONTRAST_RATIO,
      );
    }
  });

  it("占位色按声明豁免，仅限占位与装饰用途，不得达正文级", () => {
    // #9CA3AF 的豁免在 tokens.ts 注释里声明：只允许 placeholder 与装饰场景，
    // 禁用于有意义文字。把「低于正文级」钉进测试——值被改动时强迫重新审视豁免是否仍成立。
    expect(contrastRatio(THEME_COLORS.textPlaceholder, WHITE_SURFACE)).toBeLessThan(
      MIN_TEXT_CONTRAST_RATIO,
    );
  });

  it("TS 镜像与 tokens.css 的令牌值一致", () => {
    // CSS 自定义属性是唯一事实源，TS 只做镜像——镜像一旦漂移，JS 取色场景
    // （ECharts 等）就会画出与界面不一致的颜色。这里以 CSS 文件为基准逐项核对。
    const declaredValues = new Map<string, string>();
    for (const [, name, value] of tokensCssSource.matchAll(/(--[\w-]+)\s*:\s*(#[0-9a-fA-F]{6})/g)) {
      declaredValues.set(name, value);
    }

    for (const token of Object.keys(CSS_VARIABLE_BY_TOKEN) as Array<keyof typeof THEME_COLORS>) {
      const variable = CSS_VARIABLE_BY_TOKEN[token];
      const cssValue = declaredValues.get(variable);
      expect(cssValue, `${variable} 应在 tokens.css 中以十六进制色值声明`).toBeDefined();
      // 十六进制大小写不承载语义，比较前归一。
      expect(cssValue?.toLowerCase(), `${variable} 与 TS 镜像不一致`).toBe(THEME_COLORS[token].toLowerCase());
    }
  });
});
