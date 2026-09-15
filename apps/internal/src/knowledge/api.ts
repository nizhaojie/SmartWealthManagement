import { http } from "../api/http";
import type { DocumentStatus, KnowledgeDocument, KnowledgeType } from "./types";

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

export function uploadDocument(file: File, knowledgeType: KnowledgeType): Promise<KnowledgeDocument> {
  const form = new FormData();
  form.append("file", file);
  form.append("knowledge_type", knowledgeType);
  return http.postForm<KnowledgeDocument>("/api/internal/knowledge/documents", form);
}

export function deleteDocument(knowledgeId: number): Promise<KnowledgeDocument> {
  return http.delete<KnowledgeDocument>(`/api/internal/knowledge/documents/${knowledgeId}`);
}
