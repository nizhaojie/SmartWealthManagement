import { http } from "../api/http";
import type {
  AdvisoryComment,
  AdvisoryDraft,
  AdvisoryFinal,
  AdvisoryHistoryEntry,
  AdvisoryQueue,
  AdvisoryReviewStatus,
  CustomerOption,
} from "./types";

export function getQueue(): Promise<AdvisoryQueue> {
  return http.get<AdvisoryQueue>("/api/internal/advisory/queue");
}

// 顾问也能在没有客户方案请求的情况下主动为一位客户发起生成（spec story
// 「对一位客户发起方案生成」），不是只能从待生成队列里的请求进入。
export function listCustomersForPlan(): Promise<CustomerOption[]> {
  return http.get<CustomerOption[]>("/api/internal/customers");
}

export function getMyHistory(): Promise<AdvisoryHistoryEntry[]> {
  return http
    .get<{ history: AdvisoryHistoryEntry[] }>("/api/internal/advisory/history")
    .then((data) => data.history);
}

export function generatePlan(input: {
  customerId: number;
  tilt?: string | null;
  advisoryRequestId?: number | null;
}): Promise<AdvisoryDraft> {
  return http.post<AdvisoryDraft>(`/api/internal/advisory/customers/${input.customerId}/plan`, {
    tilt: input.tilt ?? null,
    advisory_request_id: input.advisoryRequestId ?? null,
  });
}

export function getDraft(draftId: number): Promise<AdvisoryDraft> {
  return http.get<AdvisoryDraft>(`/api/internal/advisory/drafts/${draftId}`);
}

export function getReviewStatus(draftId: number): Promise<AdvisoryReviewStatus> {
  return http.get<AdvisoryReviewStatus>(`/api/internal/advisory/drafts/${draftId}/review`);
}

export function getFinal(draftId: number): Promise<AdvisoryFinal> {
  return http.get<AdvisoryFinal>(`/api/internal/advisory/drafts/${draftId}/final`);
}

export function releaseDraft(
  draftId: number,
  edits: {
    candidates?: unknown[] | null;
    allocationSuggestion?: Record<string, number> | null;
    warnings?: unknown[] | null;
  },
): Promise<AdvisoryFinal> {
  return http.post<AdvisoryFinal>(`/api/internal/advisory/drafts/${draftId}/release`, {
    candidates: edits.candidates ?? null,
    allocation_suggestion: edits.allocationSuggestion ?? null,
    warnings: edits.warnings ?? null,
  });
}

export function rejectDraft(
  draftId: number,
  reason: string,
): Promise<{ draft_id: number; status: string; reason: string }> {
  return http.post(`/api/internal/advisory/drafts/${draftId}/reject`, { reason });
}

export function listComments(draftId: number): Promise<AdvisoryComment[]> {
  return http
    .get<{ comments: AdvisoryComment[] }>(`/api/internal/advisory/drafts/${draftId}/comments`)
    .then((data) => data.comments);
}

export function postComment(draftId: number, body: string): Promise<AdvisoryComment> {
  return http.post<AdvisoryComment>(`/api/internal/advisory/drafts/${draftId}/comments`, { body });
}
