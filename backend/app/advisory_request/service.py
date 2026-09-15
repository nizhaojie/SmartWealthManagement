import hashlib
import json
from datetime import datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AdvisoryRequest

STATUS_PENDING = "待处理"
STATUS_IN_PROGRESS = "处理中"
STATUS_COMPLETED = "已完成"
STATUS_CLOSED = "已关闭"

OPEN_STATUSES = (STATUS_PENDING, STATUS_IN_PROGRESS)

FILTER_KEYS = (
    "product_type",
    "risk_level",
    "min_amount",
    "min_expected_return",
    "max_term_days",
)


def _normalize_filters(filters: dict) -> dict:
    normalized: dict[str, str] = {}
    for key in FILTER_KEYS:
        value = filters.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            normalized[key] = text
    return normalized


def _condition_fingerprint(filters: dict) -> str:
    canonical = json.dumps(filters, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _request_no(now: datetime) -> str:
    return f"AR{now.strftime('%Y%m%d')}{uuid4().hex[:6].upper()}"


def _serialize(row: AdvisoryRequest) -> dict:
    return {
        "id": row.id,
        "request_no": row.request_no,
        "customer_id": row.customer_id,
        "status": row.status,
        "filters": row.filters,
        "submitted_at": row.submitted_at.isoformat(),
    }


def submit_request(db: Session, *, customer_id: int, filters: dict, now: datetime) -> dict:
    """登记一条方案请求。

    同一客户以同一筛选条件重复提交时，若已有未终态的请求，则复用它——重复点击不
    应在理财顾问的待办里堆出多张同义工单。
    """
    normalized = _normalize_filters(filters)
    fingerprint = _condition_fingerprint(normalized)

    open_request = db.scalar(
        select(AdvisoryRequest)
        .where(
            AdvisoryRequest.customer_id == customer_id,
            AdvisoryRequest.condition_fingerprint == fingerprint,
            AdvisoryRequest.status.in_(OPEN_STATUSES),
        )
        .order_by(AdvisoryRequest.id.desc())
    )
    if open_request is not None:
        return _serialize(open_request)

    row = AdvisoryRequest(
        request_no=_request_no(now),
        customer_id=customer_id,
        status=STATUS_PENDING,
        filters=normalized,
        condition_fingerprint=fingerprint,
        submitted_at=now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _serialize(row)


def list_requests(db: Session, *, customer_id: int) -> list[dict]:
    rows = db.scalars(
        select(AdvisoryRequest)
        .where(AdvisoryRequest.customer_id == customer_id)
        .order_by(AdvisoryRequest.submitted_at.desc(), AdvisoryRequest.id.desc())
    ).all()
    return [_serialize(row) for row in rows]


def list_requests_for_queue(db: Session, *, status: str | None = None) -> list[dict]:
    stmt = select(AdvisoryRequest)
    if status:
        stmt = stmt.where(AdvisoryRequest.status == status)
    rows = db.scalars(
        stmt.order_by(AdvisoryRequest.submitted_at.asc(), AdvisoryRequest.id.asc())
    ).all()
    return [_serialize(row) for row in rows]
