// 客户历史记录：只读回看本人过去的会话，复用后端 `conversation_archive` 归档。
// 列表排除当前会话（当前会话在对话页可见，历史只收「已结束的登录会话」）；
// 详情只给 role / content / citations / 时间 / `data`，后端不返回 tool_calls 与内容分类。
//
// 列表分页（ADR-0024）：会话是只增的，一页装不下时靠 `page`/`page_size` 逐页取。
// 详情内嵌的 `messages` 不分页——回看的是这一场会话本身，与列表的页长无关。
import type { PageQuery, Paginated } from "@wealth/shared";
import { http } from "../api/http";
import { queryString } from "../api/query";
import type { Citation, DataAnswer } from "./api";

export type CustomerSessionSummary = {
  session_id: string;
  title: string;
  message_count: number;
  started_at: string;
  ended_at: string;
};

export type CustomerSessionMessage = {
  role: "user" | "assistant";
  content: string;
  citations: Citation[];
  created_at: string;
  // 那一轮客户看到的结果表（ADR-0028）：归档与实时是同一张表，回看因此能重绘它；
  // 非数据问答的轮次与提问行都是 null。
  data: DataAnswer | null;
};

export type CustomerSessionDetail = {
  session_id: string;
  started_at: string;
  ended_at: string;
  messages: CustomerSessionMessage[];
};

/** 本人的历史会话一页（最后发言倒序）。`items`/`total` 由服务端给，前端不数本页条数。 */
export function listCustomerConversations(
  query: PageQuery,
): Promise<Paginated<CustomerSessionSummary>> {
  const search = queryString({ page: query.page, page_size: query.page_size });
  return http.get<Paginated<CustomerSessionSummary>>(`/api/customer/conversations${search}`);
}

export function getCustomerConversation(sessionId: string): Promise<CustomerSessionDetail> {
  return http.get<CustomerSessionDetail>(
    `/api/customer/conversations/${encodeURIComponent(sessionId)}`,
  );
}
