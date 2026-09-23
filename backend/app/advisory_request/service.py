import hashlib
import json
from datetime import datetime
from typing import cast
from uuid import uuid4

from sqlalchemy import CursorResult, select, update
from sqlalchemy.orm import Session

from app.db.models import AdvisoryRequest, Customer
from app.exceptions import AppError
from app.pagination import PageParams, count_matching

STATUS_PENDING = "待处理"
STATUS_IN_PROGRESS = "处理中"
STATUS_COMPLETED = "已完成"
STATUS_CLOSED = "已关闭"

OPEN_STATUSES = (STATUS_PENDING, STATUS_IN_PROGRESS)

REQUEST_NOT_FOUND_MESSAGE = "方案请求不存在"
REQUEST_ALREADY_CLAIMED_MESSAGE = "该方案请求已在处理中或已处理完毕"

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


def waiting_seconds(now: datetime, since: datetime) -> float:
    """一条内容在队列里等了多久。

    队列视图（待生成的方案请求、待审的投顾内容）共用一个口径：各算一遍的话，
    两个数字的含义会悄悄分叉，而它们并排显示在同一张工作台上。负数夹到 0——
    客户端时钟与服务端不一致时，等待时长不该出现负值。
    """
    return max(0.0, (now - since).total_seconds())


def _serialize(row: AdvisoryRequest) -> dict:
    # 不带 customer_id：客户由令牌圈定，响应里不需要也不该回显内部标识。
    return {
        "id": row.id,
        "request_no": row.request_no,
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


def list_requests(
    db: Session, *, customer_id: int, page: PageParams
) -> tuple[list[dict], int]:
    """客户自己的方案请求一页，最近提交的在前（ADR-0024）。

    排序键 `submitted_at` 只到秒：`id` 兜底定死同一秒提交的两条请求的先后，
    否则翻页会在两页之间来回跳。
    """
    stmt = (
        select(AdvisoryRequest)
        .where(AdvisoryRequest.customer_id == customer_id)
        .order_by(AdvisoryRequest.submitted_at.desc(), AdvisoryRequest.id.desc())
    )
    total = count_matching(db, stmt)
    rows = db.scalars(stmt.offset(page.offset).limit(page.page_size)).all()
    return [_serialize(row) for row in rows], total


def list_requests_for_queue(
    db: Session, *, status: str | None, page: PageParams, now: datetime
) -> tuple[list[dict], int]:
    """内部端的方案请求一页：顾问要看「谁在等、等了多久、什么条件」。

    与客户侧的两点不同：排序是等得最久的在前——队列型列表按等待时长倒序，也就是
    事件时间**升序**（ADR-0024 关于记录型与队列型列表的分野）；并且带上客户与
    等待时长，顾问端要凭它决定先处理哪一条。客户侧不回显客户标识，那段口径在
    `_serialize` 里，不在这里。
    """
    stmt = select(AdvisoryRequest, Customer.real_name).join(
        Customer, Customer.id == AdvisoryRequest.customer_id
    )
    if status:
        stmt = stmt.where(AdvisoryRequest.status == status)
    stmt = stmt.order_by(AdvisoryRequest.submitted_at.asc(), AdvisoryRequest.id.asc())

    total = count_matching(db, stmt)
    rows = db.execute(stmt.offset(page.offset).limit(page.page_size)).all()
    return [
        _serialize_for_queue(row, customer_name=customer_name, now=now)
        for row, customer_name in rows
    ], total


def _serialize_for_queue(row: AdvisoryRequest, *, customer_name: str, now: datetime) -> dict:
    """顾问端的一行：在客户侧那份之上补「是谁在等、等了多久」。

    客户侧不回显 `customer_id`，顾问端必须有它才能点「生成方案」——两端口径的
    差异只在这一处，`_serialize` 那份因此保持原样。
    """
    return {
        **_serialize(row),
        "customer_id": row.customer_id,
        "customer_name": customer_name,
        "waiting_seconds": waiting_seconds(now, row.submitted_at),
    }


def get_request(db: Session, request_id: int) -> AdvisoryRequest:
    request = db.get(AdvisoryRequest, request_id)
    if request is None:
        raise AppError(404, REQUEST_NOT_FOUND_MESSAGE)
    return request


def claim_request(db: Session, request_id: int) -> AdvisoryRequest:
    """把一条方案请求从「待处理」原子地切到「处理中」，语义同
    `app.advisory.review._claim`：真正兜底并发的是下面这条
    `UPDATE ... WHERE status = 待处理`，而不是先读后写。
    """
    request = get_request(db, request_id)
    if request.status != STATUS_PENDING:
        raise AppError(409, REQUEST_ALREADY_CLAIMED_MESSAGE)

    result = cast(
        CursorResult,
        db.execute(
            update(AdvisoryRequest)
            .where(AdvisoryRequest.id == request_id, AdvisoryRequest.status == STATUS_PENDING)
            .values(status=STATUS_IN_PROGRESS)
        ),
    )
    db.commit()
    if result.rowcount == 0:
        raise AppError(409, REQUEST_ALREADY_CLAIMED_MESSAGE)
    db.refresh(request)
    return request


def complete_request(db: Session, request_id: int) -> None:
    request = get_request(db, request_id)
    request.status = STATUS_COMPLETED
    db.commit()


def reopen_request(db: Session, request_id: int) -> None:
    """把一条方案请求退回「待处理」——放行失败或驳回时用，让它能被重新生成。"""
    request = get_request(db, request_id)
    request.status = STATUS_PENDING
    db.commit()
