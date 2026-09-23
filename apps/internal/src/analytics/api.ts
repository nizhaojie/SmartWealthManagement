import type { PageQuery, Paginated } from "@wealth/shared";
import { http } from "../api/http";
import { queryString } from "../api/query";
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

/** 本人的历史查询一页（留痕时间倒序）。`items`/`total` 由服务端给，前端不数本页条数。 */
export function listAnalyticsHistory(
  query: PageQuery,
): Promise<Paginated<AnalyticsHistoryItem>> {
  const search = queryString({ page: query.page, page_size: query.page_size });
  return http.get<Paginated<AnalyticsHistoryItem>>(`/api/internal/analytics/history${search}`);
}

export function listAnalyticsExamples(): Promise<AnalyticsExampleItem[]> {
  return http.get<AnalyticsExampleItem[]>("/api/internal/analytics/examples");
}
