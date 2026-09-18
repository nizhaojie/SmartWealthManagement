// 客户历史记录：只读回看本人过去的会话，复用后端 `conversation_archive` 归档。
// 列表排除当前会话（当前会话在对话页可见，历史只收「已结束的登录会话」）；
// 详情只给 role / content / citations / 时间，后端不返回 tool_calls 与内容分类。
import { http } from "../api/http";
import type { Citation } from "./api";

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
};

export type CustomerSessionDetail = {
  session_id: string;
  started_at: string;
  ended_at: string;
  messages: CustomerSessionMessage[];
};

export function listCustomerConversations(): Promise<CustomerSessionSummary[]> {
  return http.get<CustomerSessionSummary[]>("/api/customer/conversations");
}

export function getCustomerConversation(sessionId: string): Promise<CustomerSessionDetail> {
  return http.get<CustomerSessionDetail>(
    `/api/customer/conversations/${encodeURIComponent(sessionId)}`,
  );
}
