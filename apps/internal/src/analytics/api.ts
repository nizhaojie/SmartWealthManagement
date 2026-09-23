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
  // 不带会话标识时请求体里就没有这个字段——后端取登录凭证里的 sid，同一次登录
  // 的追问因此共用一个上下文。只有「清空对话」后才带一个新的标识把它换掉。
  const body: { question: string; session_id?: string } = {
    question: input.question,
  };
  if (input.sessionId) {
    body.session_id = input.sessionId;
  }
  return http.post<AnalyticsQueryResponse>("/api/internal/analytics/query", body);
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
