"""投顾助手 Agent 的生成入口：把一次生成运行推进到审核中断点。

产出以 AI 原稿的形式落库（`app.advisory.draft`），随后图用运行时的
`interrupt()` 暂停等待人工审核（`app.advisory.graph`）——本函数只发起
运行、拿到暂停前落库的原稿并返回，不关心恢复；恢复是
`app.advisory.review` 的职责。
"""

from datetime import datetime
from uuid import uuid4

import redis
from sqlalchemy.orm import Session

from app.advisory.draft import get_draft, serialize_draft
from app.advisory.graph import AdvisoryState, build_graph
from app.advisory.scoring import ALLOWED_TILTS, TILT_BALANCED
from app.advisory_request.service import claim_request, get_request, reopen_request
from app.exceptions import AppError

UNKNOWN_TILT_MESSAGE = "未知的生成侧重"
REQUEST_CUSTOMER_MISMATCH_MESSAGE = "方案请求所属客户与生成目标不一致"


def generate_advisory_plan(
    db: Session,
    cache: redis.Redis,
    *,
    customer_id: int,
    advisor_id: int,
    tilt: str | None,
    now: datetime,
    advisory_request_id: int | None = None,
) -> dict:
    resolved_tilt = tilt or TILT_BALANCED
    if resolved_tilt not in ALLOWED_TILTS:
        raise AppError(400, UNKNOWN_TILT_MESSAGE)

    if advisory_request_id is not None:
        request = get_request(db, advisory_request_id)
        if request.customer_id != customer_id:
            raise AppError(400, REQUEST_CUSTOMER_MISMATCH_MESSAGE)
        # 认领方案请求是这里唯一的锁——两位顾问同时对同一条请求点「生成」，
        # 只有一个能把状态从待处理切到处理中，另一个直接拿到 409。
        claim_request(db, advisory_request_id)

    graph = build_graph(db, cache)
    thread_id = uuid4().hex
    try:
        final_state: AdvisoryState = graph.invoke(
            {
                "customer_id": customer_id,
                "advisor_id": advisor_id,
                "tilt": resolved_tilt,
                "now": now,
                "thread_id": thread_id,
                "advisory_request_id": advisory_request_id,
            },
            {"configurable": {"thread_id": thread_id}},
        )
    except Exception:
        if advisory_request_id is not None:
            reopen_request(db, advisory_request_id)
        raise

    draft = get_draft(db, final_state["draft_id"])
    return serialize_draft(draft)
