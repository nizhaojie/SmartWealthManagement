"""审核队列：待生成的客户方案请求 + 待审核的 AI 原稿，外加顾问自己的审核历史。

两段队列分别对应两个不同的「等待」：待处理的方案请求在等顾问点「生成」，
待审核的原稿在等顾问放行或驳回。等待时长按各自的起点（提交时间 / 原稿
落库时间）现算，不落库——它随时间流逝而变化，落库反而要操心失效。

排序留给前端：数据量小，且「可排序」指的是顾问按不同列重新排列，不是
服务端要支持多种排序参数。
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.advisory.review_status import STATUS_IN_PROGRESS, STATUS_PENDING
from app.advisory_request.service import STATUS_PENDING as REQUEST_STATUS_PENDING
from app.db.models import (
    AdvisoryDraft,
    AdvisoryRequest,
    AdvisoryReview,
    AdvisoryReviewAudit,
    Customer,
)


def _waiting_seconds(now: datetime, since: datetime) -> float:
    return max(0.0, (now - since).total_seconds())


def list_queue(db: Session, now: datetime) -> dict:
    pending_requests = []
    request_rows = db.execute(
        select(AdvisoryRequest, Customer.real_name)
        .join(Customer, Customer.id == AdvisoryRequest.customer_id)
        .where(AdvisoryRequest.status == REQUEST_STATUS_PENDING)
        .order_by(AdvisoryRequest.submitted_at.asc())
    ).all()
    for request, customer_name in request_rows:
        pending_requests.append(
            {
                "id": request.id,
                "request_no": request.request_no,
                "customer_id": request.customer_id,
                "customer_name": customer_name,
                "filters": request.filters,
                "submitted_at": request.submitted_at.isoformat(),
                "waiting_seconds": _waiting_seconds(now, request.submitted_at),
            }
        )

    pending_reviews = []
    review_rows = db.execute(
        select(AdvisoryReview, AdvisoryDraft, Customer.real_name)
        .join(AdvisoryDraft, AdvisoryDraft.id == AdvisoryReview.draft_id)
        .join(Customer, Customer.id == AdvisoryDraft.customer_id)
        .where(AdvisoryReview.status.in_((STATUS_PENDING, STATUS_IN_PROGRESS)))
        .order_by(AdvisoryReview.create_time.asc())
    ).all()
    for review, draft, customer_name in review_rows:
        pending_reviews.append(
            {
                "draft_id": draft.id,
                "customer_id": draft.customer_id,
                "customer_name": customer_name,
                "status": review.status,
                "tilt": draft.tilt,
                "generated_at": draft.generated_at.isoformat(),
                "waiting_seconds": _waiting_seconds(now, review.create_time),
            }
        )

    return {"pending_requests": pending_requests, "pending_reviews": pending_reviews}


def list_my_history(db: Session, advisor_id: int) -> list[dict]:
    rows = db.execute(
        select(AdvisoryReviewAudit, AdvisoryDraft, Customer.real_name)
        .join(AdvisoryReview, AdvisoryReview.id == AdvisoryReviewAudit.review_id)
        .join(AdvisoryDraft, AdvisoryDraft.id == AdvisoryReview.draft_id)
        .join(Customer, Customer.id == AdvisoryDraft.customer_id)
        .where(AdvisoryReviewAudit.advisor_id == advisor_id)
        .order_by(AdvisoryReviewAudit.decided_at.desc())
    ).all()
    return [
        {
            "draft_id": draft.id,
            "customer_id": draft.customer_id,
            "customer_name": customer_name,
            "action": audit.action,
            "reason": audit.reason,
            "decided_at": audit.decided_at.isoformat(),
        }
        for audit, draft, customer_name in rows
    ]
