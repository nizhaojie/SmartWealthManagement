"""审核流的加锁与恢复，外加方案那一类的放行与驳回。

两类投顾内容共用同一条流水线（ADR-0020），所以这一层分两半：

- **类型无关的一半**：`get_review_by_content` / `claim_review` / `resume_review`。
  它们只认审核记录上的「内容类型 + 内容引用」，加锁加在审核记录上，续跑时按
  内容类型查表拿运行时（app.advisory.pipeline）——操作建议那一类接进来时复用
  这一半，不再写第二套加锁与恢复。
- **方案特有的一半**：`release_review` / `reject_review`。放行前要复核候选池、
  放行/驳回要带着方案请求的状态走，这些是方案载荷的性质，不该由流水线承担。

中断与恢复本身仍由各内容类型的 LangGraph 运行时承担（ADR-0007，见
app.advisory.runtime）。校验失败时绝不触碰运行时，中断保持原样，顾问改完可以重试。
"""

from datetime import datetime
from typing import cast

import redis
from langgraph.types import Command
from sqlalchemy import CursorResult, select, update
from sqlalchemy.orm import Session

from app.advisory.draft import get_draft
from app.advisory.final import get_final_by_draft_id, serialize_final
from app.advisory.pipeline import CONTENT_TYPE_PLAN, resume_graph_builder
from app.advisory.review_status import (
    ACTION_REJECT,
    ACTION_RELEASE,
    STATUS_IN_PROGRESS,
    STATUS_PENDING,
    STATUS_REJECTED,
    STATUS_RELEASED,
)
from app.advisory.runtime import has_pending_checkpoint
from app.advisory_request.service import complete_request, reopen_request
from app.db.models import AdvisoryReview, AdvisoryReviewAudit
from app.exceptions import AppError
from app.suitability.service import get_candidate_pool

REVIEW_NOT_FOUND_MESSAGE = "审核记录不存在"
ALREADY_DECIDED_MESSAGE = "该内容已完成审核"
LOCKED_MESSAGE = "该内容正在被审核，请稍后再试"
REASON_REQUIRED_MESSAGE = "驳回理由不能为空"
OUT_OF_POOL_MESSAGE = "推荐产品已不在候选池内，放行被拒绝"
REVIEW_STATE_LOST_MESSAGE = "审核状态已失效，请重新生成方案"


def get_review_by_content(db: Session, *, content_type: str, content_ref: int) -> AdvisoryReview:
    """按「内容类型 + 内容引用」取审核记录——流水线认的就是这一对标识。"""
    review = db.scalar(
        select(AdvisoryReview).where(
            AdvisoryReview.content_type == content_type,
            AdvisoryReview.content_ref == content_ref,
        )
    )
    if review is None:
        raise AppError(404, REVIEW_NOT_FOUND_MESSAGE)
    return review


def get_review_by_draft_id(db: Session, draft_id: int) -> AdvisoryReview:
    """方案的审核记录；既有 API 路径按原稿 id 寻址，这里保持不变。"""
    return get_review_by_content(db, content_type=CONTENT_TYPE_PLAN, content_ref=draft_id)


def serialize_review(review: AdvisoryReview) -> dict:
    return {"draft_id": review.draft_id, "status": review.status}


def _claim(db: Session, review: AdvisoryReview) -> AdvisoryReview:
    """把审核记录从「待审」原子地切到「处理中」，即这里的锁。

    先按当前状态给出更明确的错误，但真正兜底并发的是下面这条
    `UPDATE ... WHERE status = 待审`——它在数据库里是原子的，两个并发请求
    只有一个能把 rowcount 改成 1，另一个必然读到 0，不依赖应用层的先读后写。

    锁在审核记录上而不是在某一类载荷上，所以两类内容共用这一套并发保护。
    """
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


def claim_review(db: Session, *, content_type: str, content_ref: int) -> AdvisoryReview:
    """取一份内容的审核记录并加锁；两类内容的入口都走这里。"""
    review = get_review_by_content(db, content_type=content_type, content_ref=content_ref)
    return _claim(db, review)


def _unclaim(db: Session, review: AdvisoryReview) -> None:
    review.status = STATUS_PENDING
    db.commit()


def resume_review(
    db: Session, cache: redis.Redis, review: AdvisoryReview, resume_payload: dict
) -> None:
    """把已校验通过的决定喂给该内容类型的运行时续跑；失败就解锁，让顾问能重试。

    用哪张图由审核记录上的内容类型决定，不由调用点指定：方案的审核记录只可能
    被喂给方案的图。类型没有登记运行时时同样解锁并报错，内容回到「待审」而不是
    卡在「处理中」。
    """
    try:
        builder = resume_graph_builder(review.content_type)
        if not has_pending_checkpoint(review.thread_id):
            # 暂停状态随进程重启丢失（见 app.advisory.runtime）：没有可续跑的
            # 中断点，必须让顾问重新生成，而不是把 KeyError 漏成 500。
            raise AppError(409, REVIEW_STATE_LOST_MESSAGE)
        builder(db, cache).invoke(
            Command(resume=resume_payload),
            {"configurable": {"thread_id": review.thread_id}},
        )
    except Exception:
        _unclaim(db, review)
        raise


def record_decision(
    db: Session,
    *,
    review: AdvisoryReview,
    action: str,
    advisor_id: int,
    reason: str | None,
    now: datetime,
) -> None:
    """把一份决定落在审核记录上：置状态 + 写审核留痕 + 提交。

    两类内容的图在各自的 finalize 节点里都只做这一件事，因此写在流水线里一份
    （ADR-0020 的单流水线）：分头写两遍的话，改状态集时总有一处会漏，而漏掉的
    那一处表现为「这份内容永远停在处理中」，不会有任何断言当场失败。

    状态由动作推出，不由调用点给：动作只有放行与驳回两种（迁移里也是这么约束的），
    让调用点同时传动作与状态，就多了一次可以传错的机会。
    """
    review.status = STATUS_RELEASED if action == ACTION_RELEASE else STATUS_REJECTED
    db.add(
        AdvisoryReviewAudit(
            review_id=review.id,
            advisor_id=advisor_id,
            action=action,
            reason=reason,
            decided_at=now,
        )
    )
    db.commit()


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
    review = claim_review(db, content_type=CONTENT_TYPE_PLAN, content_ref=draft_id)
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

    resume_review(
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

    review = claim_review(db, content_type=CONTENT_TYPE_PLAN, content_ref=draft_id)
    draft = get_draft(db, draft_id)
    resume_review(
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
