/** 检查器里各块的加载态。每一块独立一份，单块失败不牵连整栏。 */
export type InspectorLoadState = "loading" | "ready" | "failed";

/**
 * 「模块自己的筛选摘要」的一行。
 *
 * 摘要卡片是通用的（标题 + 若干行 + 一句说明），业务含义全在行的文案里——
 * 风控与工单两个模块只差行内容，不值得各写一份面板。
 */
export type SummaryRow = {
  label: string;
  value: string;
  testId?: string;
};
