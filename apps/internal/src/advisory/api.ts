import type { PageQuery, Paginated } from "@wealth/shared";
import { http } from "../api/http";
import { queryString } from "../api/query";
import {
  REQUEST_STATUS_PENDING,
  type AdvisoryComment,
  type AdvisoryDraft,
  type AdvisoryFinal,
  type AdvisoryHistoryEntry,
  type AdvisoryReviewStatus,
  type PendingRequest,
  type PendingReview,
} from "./types";

/** 待审内容的一页（两类内容合并后的队列，见 `app.advisory.queue`）。 */
export function getQueue(query: PageQuery): Promise<Paginated<PendingReview>> {
  const search = queryString({ page: query.page, page_size: query.page_size });
  return http.get<Paginated<PendingReview>>(`/api/internal/advisory/queue${search}`);
}

/** 顾问自己审核过的一页，最近的在前。 */
export function getMyHistory(query: PageQuery): Promise<Paginated<AdvisoryHistoryEntry>> {
  const search = queryString({ page: query.page, page_size: query.page_size });
  return http.get<Paginated<AdvisoryHistoryEntry>>(`/api/internal/advisory/history${search}`);
}

/**
 * 待生成的方案请求一页。
 *
 * 它不是队列接口的一段：方案请求是独立列表资源，「待处理」的那些才是在等顾问
 * 点「生成」的（ADR-0024）。状态由服务端筛，`total` 才是过滤后的总数。
 */
export function listQueueRequests(query: PageQuery): Promise<Paginated<PendingRequest>> {
  const search = queryString({
    status: REQUEST_STATUS_PENDING,
    page: query.page,
    page_size: query.page_size,
  });
  return http.get<Paginated<PendingRequest>>(`/api/internal/advisory-requests${search}`);
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
