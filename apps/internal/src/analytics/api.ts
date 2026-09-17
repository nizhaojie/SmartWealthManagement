import { http } from "../api/http";
import type {
  AnalyticsExampleItem,
  AnalyticsHistoryItem,
  AnalyticsQueryInput,
  AnalyticsQueryResponse,
} from "./types";

export function runAnalyticsQuery(
  input: AnalyticsQueryInput,
): Promise<AnalyticsQueryResponse> {
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
