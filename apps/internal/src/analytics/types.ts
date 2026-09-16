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
