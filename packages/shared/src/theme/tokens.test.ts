// 令牌的可用性不靠肉眼挑：文本类与涨跌色必须对白底达到 WCAG 正文级对比度。
// 与 chart/palette.test.ts 同一套门槛——改色值前先跑这个测试。

import { describe, expect, it } from "vitest";
import { contrastRatio, parseHexColor } from "../chart/color";
import tokensCssSource from "./tokens.css?raw";
import { MIN_TEXT_CONTRAST_RATIO, THEME_COLORS } from "./tokens";

const WHITE_SURFACE = "#FFFFFF";

/** 每个色彩令牌在 tokens.css 里对应的自定义属性名。 */
const CSS_VARIABLE_BY_TOKEN: Record<keyof typeof THEME_COLORS, string> = {
  primary: "--wm-color-primary",
  primaryTint: "--wm-color-primary-tint",
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

/** tokens.css 里「淡染底上的文字」那条派生式。 */
const PRIMARY_STRONG_DERIVATION =
  /--wm-color-primary-strong:\s*color-mix\(in srgb, var\(--wm-color-primary\)\s*([\d.]+)%,\s*black\)/;

/**
 * 复算 color-mix(in srgb, hex 比例, black)：sRGB 通道按比例线性插值后取整。
 * 派生式留在 CSS 里，这里只做等价的算术，避免把派生结果抄成第二份硬编码色。
 */
function mixWithBlack(hex: string, ratio: number): string {
  const { red, green, blue } = parseHexColor(hex);
  const toHex = (channel: number) =>
    Math.round(channel * ratio)
      .toString(16)
      .padStart(2, "0");
  return `#${toHex(red)}${toHex(green)}${toHex(blue)}`;
}

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

  it("淡染底上的文字令牌对主色淡染底达到 WCAG 正文级对比度", () => {
    // 这是 --wm-color-primary-strong 存在的理由：02 的 #1677ff on #e8f1ff 只有 3.61:1。
    // 派生式写在 CSS 里，这里按同一比例复算，改比例会同时被两边看见。
    const derivation = PRIMARY_STRONG_DERIVATION.exec(tokensCssSource);
    expect(
      derivation,
      "--wm-color-primary-strong 应以 color-mix(in srgb, var(--wm-color-primary) N%, black) 派生",
    ).not.toBeNull();

    const strong = mixWithBlack(THEME_COLORS.primary, Number(derivation?.[1]) / 100);
    expect(contrastRatio(strong, THEME_COLORS.primaryTint)).toBeGreaterThanOrEqual(
      MIN_TEXT_CONTRAST_RATIO,
    );
  });

  it("占位色按声明豁免，仅限占位与装饰用途，不得达正文级", () => {
    // #A3ACBD 的豁免在 tokens.ts 注释里声明：只允许 placeholder 与装饰场景，
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
