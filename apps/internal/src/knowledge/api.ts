import type { PageQuery, Paginated } from "@wealth/shared";
import { http } from "../api/http";
import { queryString } from "../api/query";
import type { DocumentStatus, KnowledgeDocument, KnowledgeType, SearchResult } from "./types";

export type DocumentFilters = {
  knowledgeType?: KnowledgeType;
  status?: DocumentStatus;
};

/**
 * 文档列表的一页（ADR-0024）。类型与状态筛选交给服务端：分页之后前端手里只有这一页，
 * 本地筛选只筛得动这一页，而「共 N 条」是**过滤后**的份数。
 */
export function listDocuments(
  filters: DocumentFilters = {},
  query: PageQuery,
): Promise<Paginated<KnowledgeDocument>> {
  const search = queryString({
    knowledge_type: filters.knowledgeType,
    status: filters.status,
    page: query.page,
    page_size: query.page_size,
  });
  return http.get<Paginated<KnowledgeDocument>>(`/api/internal/knowledge/documents${search}`);
}

/** 上传走 multipart：`knowledge_type` 必填，`title` 可选（缺省时后端取文件名）。 */
export function uploadDocument(
  file: File,
  knowledgeType: KnowledgeType,
  title?: string,
): Promise<KnowledgeDocument> {
  const form = new FormData();
  form.append("file", file);
  form.append("knowledge_type", knowledgeType);
  if (title) {
    form.append("title", title);
  }
  return http.postForm<KnowledgeDocument>("/api/internal/knowledge/documents", form);
}

export function deleteDocument(knowledgeId: number): Promise<KnowledgeDocument> {
  return http.delete<KnowledgeDocument>(`/api/internal/knowledge/documents/${knowledgeId}`);
}

export type SearchInput = {
  query: string;
  knowledgeType?: KnowledgeType;
};

export function searchKnowledge(input: SearchInput): Promise<SearchResult> {
  return http.post<SearchResult>("/api/internal/knowledge/search", {
    query: input.query,
    knowledge_type: input.knowledgeType,
    top_k: 10,
  });
}
