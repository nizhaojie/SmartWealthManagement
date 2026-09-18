import { http } from "../api/http";
import type { DocumentStatus, KnowledgeDocument, KnowledgeType, SearchResult } from "./types";

export type DocumentFilters = {
  knowledgeType?: KnowledgeType;
  status?: DocumentStatus;
};

export function listDocuments(filters: DocumentFilters = {}): Promise<KnowledgeDocument[]> {
  const params = new URLSearchParams();
  if (filters.knowledgeType) {
    params.set("knowledge_type", filters.knowledgeType);
  }
  if (filters.status) {
    params.set("status", filters.status);
  }
  const query = params.toString();
  return http.get<KnowledgeDocument[]>(
    `/api/internal/knowledge/documents${query ? `?${query}` : ""}`,
  );
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
