"""操作建议的放行与驳回：审核流水线在操作建议这一侧的入口。

放行与驳回只开放给理财顾问（CONTEXT「客户经理」：发起与放行是两件事，资质要求在
系统里是硬的）。角色在路由依赖里声明（`require_employee_role`），这里只负责把决定
喂回那条生成运行——恢复用哪张图由内容类型决定，加锁与恢复都是流水线公共的那一半
（`app.advisory.review`），这里不写第二套。

与方案那一侧（`app.advisory.review` 的 `release_review` / `reject_review`）的区别只有
一处：操作建议没有可编辑的字段，**放行不产生第二份定稿**（#06），因此这里没有候选池
复核、也不落定稿——审核记录上的「已放行」本身就是送达依据，客户侧按它过滤
（`app.operation_advice.decision`）。
"""

from datetime import datetime

import redis
from sqlalchemy.orm import Session

from app.advisory.pipeline import CONTENT_TYPE_OPERATION_ADVICE
from app.advisory.review import REASON_REQUIRED_MESSAGE, claim_review, resume_review
from app.advisory.review_status import ACTION_REJECT, ACTION_RELEASE
from app.db.models import AdvisoryReview
from app.exceptions import AppError


def release_advice(
    db: Session,
    cache: redis.Redis,
    *,
    advice_id: int,
    advisor_id: int,
    now: datetime,
) -> dict:
    """理财顾问放行一条操作建议：审核记录置为已放行，建议从此进入客户可见集合。"""
    review = _claim_advice(db, advice_id)
    resume_review(
        db,
        cache,
        review,
        {"action": ACTION_RELEASE, "advisor_id": advisor_id, "now": now},
    )
    db.refresh(review)
    return {"id": advice_id, "status": review.status}


def reject_advice(
    db: Session,
    cache: redis.Redis,
    *,
    advice_id: int,
    advisor_id: int,
    reason: str | None,
    now: datetime,
) -> dict:
    """理财顾问驳回一条操作建议：理由必填——顾问审的就是这份原稿。"""
    if not (reason and reason.strip()):
        raise AppError(400, REASON_REQUIRED_MESSAGE)
    stripped = reason.strip()

    review = _claim_advice(db, advice_id)
    resume_review(
        db,
        cache,
        review,
        {
            "action": ACTION_REJECT,
            "reason": stripped,
            "advisor_id": advisor_id,
            "now": now,
        },
    )
    db.refresh(review)
    return {"id": advice_id, "status": review.status, "reason": stripped}


def _claim_advice(db: Session, advice_id: int) -> AdvisoryReview:
    """取这条建议的审核记录并加锁；不存在时由流水线回「审核记录不存在」。"""
    return claim_review(
        db, content_type=CONTENT_TYPE_OPERATION_ADVICE, content_ref=advice_id
    )
