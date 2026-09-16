import { http } from "../api/http";
import type {
  AnalyticsExampleItem,
  AnalyticsHistoryItem,
  AnalyticsQueryResponse,
} from "./types";

export type AskInput = {
  question: string;
  // 多轮追问的会话标识：同一会话内上一轮问题进入生成上下文。
  sessionId: string;
};

export function runAnalyticsQuery(input: AskInput): Promise<AnalyticsQueryResponse> {
  return http.post<AnalyticsQueryResponse>("/api/internal/analytics/query", {
    question: input.question,
    session_id: input.sessionId,
  });
}

export function listAnalyticsHistory(): Promise<AnalyticsHistoryItem[]> {
  return http.get<AnalyticsHistoryItem[]>("/api/internal/analytics/history");
}

export function listAnalyticsExamples(): Promise<AnalyticsExampleItem[]> {
  return http.get<AnalyticsExampleItem[]>("/api/internal/analytics/examples");
}
