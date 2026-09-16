"""投顾助手 Agent 的生成入口：候选池内排序、配置建议与画像警示。

产出以 AI 原稿的形式落库（`app.advisory.draft`），落库后不可修改。内容
分类固定为投顾内容——这份 Agent 配置里的工具全是推荐类工具（候选池排序、
配置建议），调用了它们即产出投顾内容，不由模型自己声明。免责声明由
模板附加（`app.agent.classification`），不依赖模型记得写。
"""

from datetime import datetime

import redis
from sqlalchemy.orm import Session

from app.advisory.draft import DraftContent, record_draft, serialize_draft
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
    advisor_id: int,
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

    draft = record_draft(
        db,
        DraftContent(
            customer_id=customer_id,
            advisor_id=advisor_id,
            tilt=resolved_tilt,
            content_classification=ADVISORY_CONFIG.content_classification_default,
            candidates=[
                _serialize_candidate(candidate) for candidate in final_state["candidates"]
            ],
            allocation_suggestion=final_state["allocation_suggestion"],
            warnings=final_state["warnings"],
            profile_computed_at=datetime.fromisoformat(final_state["profile"]["computed_at"]),
            candidate_pool_snapshot=final_state["candidate_pool"],
            generated_at=now,
        ),
    )
    return serialize_draft(draft)
