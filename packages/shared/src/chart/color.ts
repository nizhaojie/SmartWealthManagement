// 颜色的度量：相对亮度、对比度、色相。
//
// 分类色板的可读性不能靠肉眼判断，这里提供 WCAG 定义的相对亮度与对比度，
// 以及 HSL 色相角，供色板校验脚本与测试断言使用。

export type Rgb = { red: number; green: number; blue: number };

const HEX_COLOR_PATTERN = /^#([0-9a-fA-F]{6})$/;

export function parseHexColor(hex: string): Rgb {
  const matched = HEX_COLOR_PATTERN.exec(hex.trim());
  if (matched === null) {
    throw new Error(`不是 #rrggbb 形式的颜色值: ${hex}`);
  }
  const value = Number.parseInt(matched[1], 16);
  return {
    red: (value >> 16) & 0xff,
    green: (value >> 8) & 0xff,
    blue: value & 0xff,
  };
}

function toLinear(channel: number): number {
  const ratio = channel / 255;
  return ratio <= 0.04045 ? ratio / 12.92 : ((ratio + 0.055) / 1.055) ** 2.4;
}

/** WCAG 2.1 相对亮度，取值 0（黑）到 1（白）。 */
export function relativeLuminance(hex: string): number {
  const { red, green, blue } = parseHexColor(hex);
  return (
    0.2126 * toLinear(red) + 0.7152 * toLinear(green) + 0.0722 * toLinear(blue)
  );
}

/** WCAG 2.1 对比度，取值 1（完全相同）到 21（黑白）。 */
export function contrastRatio(first: string, second: string): number {
  const lighter = Math.max(relativeLuminance(first), relativeLuminance(second));
  const darker = Math.min(relativeLuminance(first), relativeLuminance(second));
  return (lighter + 0.05) / (darker + 0.05);
}

/** HSL 色相角，取值 0 到 360（不含）。 */
export function hueDegrees(hex: string): number {
  const { red, green, blue } = parseHexColor(hex);
  const [r, g, b] = [red / 255, green / 255, blue / 255];
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const delta = max - min;
  if (delta === 0) return 0;

  let hue: number;
  if (max === r) hue = ((g - b) / delta) % 6;
  else if (max === g) hue = (b - r) / delta + 2;
  else hue = (r - g) / delta + 4;

  hue *= 60;
  return hue < 0 ? hue + 360 : hue;
}

/** 两个色相角在色环上的最短夹角，取值 0 到 180。 */
export function hueDistance(firstDegrees: number, secondDegrees: number): number {
  const raw = Math.abs(firstDegrees - secondDegrees) % 360;
  return raw > 180 ? 360 - raw : raw;
}
