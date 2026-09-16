"""审核流的放行与驳回：加锁、放行前重新校验候选池、驱动运行时恢复。

中断与恢复本身由 app.advisory.graph 的 LangGraph 运行时承担（ADR-0007，
见 app.advisory.runtime）；这里只做恢复前必须由服务端把关的业务规则——
并发加锁、候选池复核、驳回理由必填——校验通过才把决定喂给运行时续跑。
校验失败时绝不触碰运行时，中断保持原样，顾问改完可以重试。
"""

from datetime import datetime
from typing import cast

import redis
from langgraph.types import Command
from sqlalchemy import CursorResult, select, update
from sqlalchemy.orm import Session

from app.advisory.draft import get_draft
from app.advisory.final import get_final_by_draft_id, serialize_final
from app.advisory.graph import build_graph
from app.advisory.review_status import (
    ACTION_REJECT,
    ACTION_RELEASE,
    STATUS_IN_PROGRESS,
    STATUS_PENDING,
    STATUS_REJECTED,
)
from app.advisory_request.service import complete_request, reopen_request
from app.db.models import AdvisoryReview
from app.exceptions import AppError
from app.suitability.service import get_candidate_pool

REVIEW_NOT_FOUND_MESSAGE = "审核记录不存在"
ALREADY_DECIDED_MESSAGE = "该内容已完成审核"
LOCKED_MESSAGE = "该内容正在被审核，请稍后再试"
REASON_REQUIRED_MESSAGE = "驳回理由不能为空"
OUT_OF_POOL_MESSAGE = "推荐产品已不在候选池内，放行被拒绝"


def get_review_by_draft_id(db: Session, draft_id: int) -> AdvisoryReview:
    review = db.scalar(select(AdvisoryReview).where(AdvisoryReview.draft_id == draft_id))
    if review is None:
        raise AppError(404, REVIEW_NOT_FOUND_MESSAGE)
    return review


def serialize_review(review: AdvisoryReview) -> dict:
    return {"draft_id": review.draft_id, "status": review.status}


def _claim(db: Session, draft_id: int) -> AdvisoryReview:
    """把审核记录从「待审」原子地切到「处理中」，即这里的锁。

    先按当前状态给出更明确的错误，但真正兜底并发的是下面这条
    `UPDATE ... WHERE status = 待审`——它在数据库里是原子的，两个并发请求
    只有一个能把 rowcount 改成 1，另一个必然读到 0，不依赖应用层的先读后写。
    """
    review = get_review_by_draft_id(db, draft_id)
    if review.status == STATUS_IN_PROGRESS:
        raise AppError(409, LOCKED_MESSAGE)
    if review.status != STATUS_PENDING:
        raise AppError(409, ALREADY_DECIDED_MESSAGE)

    result = cast(
        CursorResult,
        db.execute(
            update(AdvisoryReview)
            .where(AdvisoryReview.id == review.id, AdvisoryReview.status == STATUS_PENDING)
            .values(status=STATUS_IN_PROGRESS)
        ),
    )
    db.commit()
    if result.rowcount == 0:
        raise AppError(409, LOCKED_MESSAGE)
    db.refresh(review)
    return review


def _unclaim(db: Session, review: AdvisoryReview) -> None:
    review.status = STATUS_PENDING
    db.commit()


def _resume(db: Session, cache: redis.Redis, review: AdvisoryReview, resume_payload: dict) -> None:
    """把已校验通过的决定喂给运行时续跑；失败就解锁，让顾问能重试。"""
    graph = build_graph(db, cache)
    try:
        graph.invoke(
            Command(resume=resume_payload),
            {"configurable": {"thread_id": review.thread_id}},
        )
    except Exception:
        _unclaim(db, review)
        raise


def release_review(
    db: Session,
    cache: redis.Redis,
    *,
    draft_id: int,
    advisor_id: int,
    now: datetime,
    candidates: list[dict] | None,
    allocation_suggestion: dict | None,
    warnings: list[dict] | None,
) -> dict:
    review = _claim(db, draft_id)
    draft = get_draft(db, draft_id)

    final_candidates = candidates if candidates is not None else draft.candidates
    final_allocation = (
        allocation_suggestion if allocation_suggestion is not None else draft.allocation_suggestion
    )
    final_warnings = warnings if warnings is not None else draft.warnings

    pool = get_candidate_pool(db, customer_id=draft.customer_id, now=now)
    allowed_codes = {item["product_code"] for item in pool["products"]}
    out_of_pool = any(item.get("product_code") not in allowed_codes for item in final_candidates)
    if out_of_pool:
        _unclaim(db, review)
        raise AppError(400, OUT_OF_POOL_MESSAGE)

    _resume(
        db,
        cache,
        review,
        {
            "action": ACTION_RELEASE,
            "candidates": final_candidates,
            "allocation_suggestion": final_allocation,
            "warnings": final_warnings,
            "advisor_id": advisor_id,
            "now": now,
        },
    )

    if draft.advisory_request_id is not None:
        complete_request(db, draft.advisory_request_id)

    return serialize_final(db, get_final_by_draft_id(db, draft_id))


def reject_review(
    db: Session,
    cache: redis.Redis,
    *,
    draft_id: int,
    advisor_id: int,
    reason: str | None,
    now: datetime,
) -> dict:
    if not (reason and reason.strip()):
        raise AppError(400, REASON_REQUIRED_MESSAGE)
    stripped_reason = reason.strip()

    review = _claim(db, draft_id)
    draft = get_draft(db, draft_id)
    _resume(
        db,
        cache,
        review,
        {
            "action": ACTION_REJECT,
            "reason": stripped_reason,
            "advisor_id": advisor_id,
            "now": now,
        },
    )

    if draft.advisory_request_id is not None:
        # 驳回意味着这份原稿不合格，方案还没出具——退回待处理，让它能被
        # 重新生成，而不是悬在处理中或被当成已完成。
        reopen_request(db, draft.advisory_request_id)

    db.refresh(review)
    return {"draft_id": draft_id, "status": STATUS_REJECTED, "reason": stripped_reason}
