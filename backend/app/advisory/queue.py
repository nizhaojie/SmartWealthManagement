"""审核队列：待生成的客户方案请求 + 待审核的投顾内容，外加顾问自己的审核历史。

两段队列分别对应两个不同的「等待」：待处理的方案请求在等顾问点「生成」，
待审核的内容在等顾问放行或驳回。等待时长按各自的起点（提交时间 / 原稿落库
时间）现算，不落库——它随时间流逝而变化，落库反而要操心失效。

待审队列按内容类型无关地合并两类内容（ADR-0020）：审核是同一类工作，分两个
队列只会让顾问漏看一半。每条都带 `content_type` 标注，队列因此不必知道载荷
长什么样就知道面前是方案还是操作建议。方案的载荷与操作建议的载荷分表，所以
合并发生在这一层——按类型各查一次再按等待时长排序，而不是硬 JOIN 到某张表上
（那会让另一类内容整批消失，且不会报错）。

排序留给前端：数据量小，且「可排序」指的是顾问按不同列重新排列，不是
服务端要支持多种排序参数。
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.advisory.pipeline import CONTENT_TYPE_OPERATION_ADVICE, CONTENT_TYPE_PLAN
from app.advisory.review_status import STATUS_IN_PROGRESS, STATUS_PENDING
from app.advisory_request.service import STATUS_PENDING as REQUEST_STATUS_PENDING
from app.db.models import (
    AdvisoryDraft,
    AdvisoryRequest,
    AdvisoryReview,
    AdvisoryReviewAudit,
    Customer,
    OperationAdviceDraft,
    Product,
)

_PENDING_STATUSES = (STATUS_PENDING, STATUS_IN_PROGRESS)


def _waiting_seconds(now: datetime, since: datetime) -> float:
    return max(0.0, (now - since).total_seconds())


def _ordered_entries(rows: list[tuple[datetime, dict]], *, newest_first: bool) -> list[dict]:
    """按时刻排好序再丢掉排序键——它是收集时的临时坐标，不属于返回的行。"""
    rows.sort(key=lambda row: row[0], reverse=newest_first)
    return [entry for _moment, entry in rows]


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

    return {"pending_requests": pending_requests, "pending_reviews": _list_pending_reviews(db, now)}


def _list_pending_reviews(db: Session, now: datetime) -> list[dict]:
    """待审的两类内容合成一条按等待时长排序的队列。"""
    rows: list[tuple[datetime, dict]] = []

    plan_rows = db.execute(
        select(AdvisoryReview, AdvisoryDraft, Customer.real_name)
        .join(AdvisoryDraft, AdvisoryDraft.id == AdvisoryReview.content_ref)
        .join(Customer, Customer.id == AdvisoryDraft.customer_id)
        .where(
            AdvisoryReview.content_type == CONTENT_TYPE_PLAN,
            AdvisoryReview.status.in_(_PENDING_STATUSES),
        )
    ).all()
    for review, draft, customer_name in plan_rows:
        rows.append(
            (
                review.create_time,
                {
                    "content_type": CONTENT_TYPE_PLAN,
                    "content_ref": review.content_ref,
                    "draft_id": draft.id,
                    "customer_id": draft.customer_id,
                    "customer_name": customer_name,
                    "status": review.status,
                    "tilt": draft.tilt,
                    "generated_at": draft.generated_at.isoformat(),
                    "waiting_seconds": _waiting_seconds(now, review.create_time),
                },
            )
        )

    advice_rows = db.execute(
        select(AdvisoryReview, OperationAdviceDraft, Customer.real_name, Product.product_name)
        # 产品外连接：产品不在目录里只该少一个名字，不该让这条建议整行消失。
        .join(OperationAdviceDraft, OperationAdviceDraft.id == AdvisoryReview.content_ref)
        .join(Customer, Customer.id == OperationAdviceDraft.customer_id)
        .outerjoin(Product, Product.product_code == OperationAdviceDraft.product_code)
        .where(
            AdvisoryReview.content_type == CONTENT_TYPE_OPERATION_ADVICE,
            AdvisoryReview.status.in_(_PENDING_STATUSES),
        )
    ).all()
    for review, advice, customer_name, product_name in advice_rows:
        rows.append(
            (
                review.create_time,
                {
                    "content_type": CONTENT_TYPE_OPERATION_ADVICE,
                    "content_ref": review.content_ref,
                    "customer_id": advice.customer_id,
                    "customer_name": customer_name,
                    "status": review.status,
                    "generated_at": advice.generated_at.isoformat(),
                    "waiting_seconds": _waiting_seconds(now, review.create_time),
                    # 操作建议的载荷摘要：顾问看队列时要知道它是哪个产品、什么方向、
                    # 多少钱——它不是方案的候选池，没有第二层可展开的东西。
                    "product_code": advice.product_code,
                    "product_name": product_name,
                    "direction": advice.direction,
                    "amount": format(advice.amount, "f"),
                },
            )
        )

    return _ordered_entries(rows, newest_first=False)


def list_my_history(db: Session, advisor_id: int) -> list[dict]:
    """顾问自己的审核历史，同样覆盖两类内容——只记一半等于另一半的审核没发生过。"""
    rows: list[tuple[datetime, dict]] = []

    plan_rows = db.execute(
        select(AdvisoryReviewAudit, AdvisoryReview, AdvisoryDraft, Customer.real_name)
        .join(AdvisoryReview, AdvisoryReview.id == AdvisoryReviewAudit.review_id)
        .join(AdvisoryDraft, AdvisoryDraft.id == AdvisoryReview.content_ref)
        .join(Customer, Customer.id == AdvisoryDraft.customer_id)
        .where(
            AdvisoryReviewAudit.advisor_id == advisor_id,
            AdvisoryReview.content_type == CONTENT_TYPE_PLAN,
        )
    ).all()
    for audit, review, draft, customer_name in plan_rows:
        rows.append(
            (
                audit.decided_at,
                {
                    "content_type": CONTENT_TYPE_PLAN,
                    "content_ref": review.content_ref,
                    "draft_id": draft.id,
                    "customer_id": draft.customer_id,
                    "customer_name": customer_name,
                    "action": audit.action,
                    "reason": audit.reason,
                    "decided_at": audit.decided_at.isoformat(),
                },
            )
        )

    advice_rows = db.execute(
        select(AdvisoryReviewAudit, AdvisoryReview, OperationAdviceDraft, Customer.real_name)
        .join(AdvisoryReview, AdvisoryReview.id == AdvisoryReviewAudit.review_id)
        .join(OperationAdviceDraft, OperationAdviceDraft.id == AdvisoryReview.content_ref)
        .join(Customer, Customer.id == OperationAdviceDraft.customer_id)
        .where(
            AdvisoryReviewAudit.advisor_id == advisor_id,
            AdvisoryReview.content_type == CONTENT_TYPE_OPERATION_ADVICE,
        )
    ).all()
    for audit, review, advice, customer_name in advice_rows:
        rows.append(
            (
                audit.decided_at,
                {
                    "content_type": CONTENT_TYPE_OPERATION_ADVICE,
                    "content_ref": review.content_ref,
                    "customer_id": advice.customer_id,
                    "customer_name": customer_name,
                    "action": audit.action,
                    "reason": audit.reason,
                    "decided_at": audit.decided_at.isoformat(),
                },
            )
        )

    return _ordered_entries(rows, newest_first=True)
