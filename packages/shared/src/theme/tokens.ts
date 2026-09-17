// UI 设计令牌的 TS 只读镜像，供 ECharts 等 JS 取色场景使用。
// 唯一事实源是同目录的 tokens.css（:root 自定义属性）；这里只镜像色彩——
// 间距/圆角/阴影没有 JS 消费方，留在 CSS 层。

/** 文字类元素对底色要求的最低对比度（WCAG 正文级）。 */
export const MIN_TEXT_CONTRAST_RATIO = 4.5;

/** 主题色彩令牌。键名对应 tokens.css 的 --wm-* 变量，改值需两处同步并跑 tokens.test.ts。 */
export const THEME_COLORS = {
  primary: "#1F6FEB",
  up: "#C81E1E",
  down: "#1E7A46",
  success: "#1E7A46",
  warning: "#B45309",
  danger: "#C81E1E",
  textPrimary: "#1F2937",
  textSecondary: "#374151",
  textMuted: "#6B7280",
  // 豁免声明：#9CA3AF 对白底仅 2.54:1，不满足正文级——仅限 placeholder 与装饰用途，
  // 禁用于任何承载信息的文字（见 spec「设计令牌层」）。
  textPlaceholder: "#9CA3AF",
  pageBackground: "#F5F7FA",
  cardSurface: "#FFFFFF",
  border: "#E5E7EB",
  hairline: "#EEF0F3",
} as const;
