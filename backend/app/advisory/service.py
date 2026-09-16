"""投顾助手 Agent 的生成入口：候选池内排序、配置建议与画像警示。

产出目前只是即时计算结果，尚未落库——AI 原稿的落库、内容分类与免责声明
是 `AI 原稿落库与内容分类`（下一个 issue）的范围，这里不提前实现。
"""

from datetime import datetime

import redis
from sqlalchemy.orm import Session

from app.advisory.graph import AdvisoryState, build_graph
from app.advisory.scoring import ALLOWED_TILTS, TILT_BALANCED
from app.agent.config import ADVISORY_CONFIG
from app.exceptions import AppError

UNKNOWN_TILT_MESSAGE = "未知的生成侧重"


def _serialize_candidate(candidate: dict) -> dict:
    return {**candidate, "expected_return": format(candidate["expected_return"], "f")}


def generate_advisory_plan(
    db: Session,
    cache: redis.Redis,
    *,
    customer_id: int,
    tilt: str | None,
    now: datetime,
) -> dict:
    resolved_tilt = tilt or TILT_BALANCED
    if resolved_tilt not in ALLOWED_TILTS:
        raise AppError(400, UNKNOWN_TILT_MESSAGE)

    graph = build_graph(db, cache)
    final_state: AdvisoryState = graph.invoke(
        {"customer_id": customer_id, "tilt": resolved_tilt, "now": now}
    )

    return {
        "customer_id": customer_id,
        "tilt": resolved_tilt,
        "generated_at": now.isoformat(),
        "content_classification": ADVISORY_CONFIG.content_classification_default,
        "candidates": [_serialize_candidate(candidate) for candidate in final_state["candidates"]],
        "allocation_suggestion": final_state["allocation_suggestion"],
        "warnings": final_state["warnings"],
    }
