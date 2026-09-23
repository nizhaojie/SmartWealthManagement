"""待审内容队列（两类内容合并）与顾问自己的审核历史。

队列是「等待最久的内容排在最前」的工作单：按内容类型无关地合并两类内容
（ADR-0020），审核是同一类工作，分两个队列只会让顾问漏看一半。每条都带
`content_type` 标注，队列因此不必知道载荷长什么样就知道面前是方案还是操作
建议。方案的载荷与操作建议的载荷分表，所以合并发生在这一层——按类型各查
一次再按等待时长排序，而不是硬 JOIN 到某张表上（那会让另一类内容整批消失，
且不会报错）。

待处理的方案请求不在这里：它与本模块的两段列表不是同一批记录，且它本身就是
一张表上的列表资源，走 `app.advisory_request.service` 与
`GET /api/internal/advisory-requests`（ADR-0024）。两个「等待」各自的起点
（提交时间 / 原稿落库时间）仍按同样的口径现算，不落库——等待时长随时间流逝
而变化，落库反而要操心失效。

两段列表都在内存里排序后交给 `pagination.paginate`（ADR-0024）：合并发生在
Python 这一层，`total` 是合并后的条数，排序键因此必须是**全序**的——只有时刻
的话，同一秒落库的两条内容在两次请求里可以换位，翻页就会把一条读两次、另一条
谁也读不到。标识（内容类型 + 内容引用）是那个兜底键。

极性是「队列型」的那一边：等得最久的排在前面，也就是事件时间**升序**（见
ADR-0024 关于记录型与队列型列表的分野）。审核是接着做的工作，让最新的那条
插到最前面，会让最该处理的内容一直沉在最后一页。
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.advisory.pipeline import CONTENT_TYPE_OPERATION_ADVICE, CONTENT_TYPE_PLAN
from app.advisory.review_status import STATUS_IN_PROGRESS, STATUS_PENDING
from app.advisory_request.service import waiting_seconds
from app.db.models import (
    AdvisoryDraft,
    AdvisoryReview,
    AdvisoryReviewAudit,
    Customer,
    OperationAdviceDraft,
    Product,
)

_PENDING_STATUSES = (STATUS_PENDING, STATUS_IN_PROGRESS)


def _ordered_entries(rows: list[tuple[datetime, dict]], *, newest_first: bool) -> list[dict]:
    """按「时刻 + 内容标识」排好序再丢掉排序键——它是收集时的临时坐标，不属于返回的行。

    兜底键不能省：`create_time` 与 `decided_at` 都只到秒，同一秒里的两条内容若没有
    确定的先后，翻页时会重读或漏读（两页看起来都正常）。
    """
    rows.sort(
        key=lambda row: (row[0], row[1]["content_type"], row[1]["content_ref"]),
        reverse=newest_first,
    )
    return [entry for _moment, entry in rows]


def list_queue(db: Session, now: datetime) -> list[dict]:
    """待审的两类内容合成一条按等待时长排序的队列（等待最久在前）；切片交给调用方。"""
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
                    "waiting_seconds": waiting_seconds(now, review.create_time),
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
                    "waiting_seconds": waiting_seconds(now, review.create_time),
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
