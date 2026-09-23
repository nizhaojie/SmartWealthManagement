// 受限查询的提问输入：问题 + 多轮追问的会话标识。数据分析与风控问答共用同一
// 形状——两条路径是同一链条上的两份 Agent 配置。
export type AnalyticsQueryInput = {
  question: string;
  /**
   * 会话标识。**唯一的用途是覆盖**：缺省时不送出去，后端取登录凭证里的 sid，
   * 于是同一次登录的追问共用一个上下文，刷新与切模块都不打断。只有界面
   * 「清空对话」之后才带一个新的标识，用它把上下文换掉。
   * 风控问答是另一份会话语义：它自持页面级标识，每次提问都带。
   */
  sessionId?: string;
};

export type AnalyticsQueryResponse = {
  question: string;
  sql: string;
  columns: string[];
  rows: unknown[][];
  row_count: number;
  truncated: boolean;
  views: string[];
  interpretation: string;
  content_classification: string;
  /** 只在投顾内容时非空：事实性内容不带免责声明。 */
  disclaimer: string | null;
};

export type AnalyticsHistoryItem = {
  id: number;
  question: string;
  sql: string | null;
  status: string;
  row_count: number | null;
  truncated: boolean;
  error_code: number | null;
  create_time: string;
};

export type AnalyticsExampleItem = {
  question: string;
};
