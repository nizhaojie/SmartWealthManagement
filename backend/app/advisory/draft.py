"""AI 原稿的落库与只读读取。

只提供 record 与 get，没有 update——原稿落库后不可修改，是日后举证
「审核是实质性的」的依据：如果连这里都能悄悄改一行，举证就没有意义。
顾问编辑原稿会产生新的版本（顾问定稿），那是审核流（下一个 issue）的
范围，不在这张表上做。
"""

from datetime import datetime
from typing import TypedDict

from sqlalchemy.orm import Session

from app.agent.classification import disclaimer_for
from app.db.models import AdvisoryDraft
from app.exceptions import AppError

DRAFT_NOT_FOUND_MESSAGE = "AI 原稿不存在"


class DraftContent(TypedDict):
    """一份 AI 原稿的全部内容——这些字段总是一起产生、一起落库，不单独存在。"""

    customer_id: int
    advisor_id: int
    tilt: str
    content_classification: str
    candidates: list[dict]
    allocation_suggestion: dict
    warnings: list[dict]
    profile_computed_at: datetime
    candidate_pool_snapshot: dict
    generated_at: datetime
    advisory_request_id: int | None


def record_draft(db: Session, content: DraftContent) -> AdvisoryDraft:
    draft = AdvisoryDraft(**content)
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


def get_draft(db: Session, draft_id: int) -> AdvisoryDraft:
    draft = db.get(AdvisoryDraft, draft_id)
    if draft is None:
        raise AppError(404, DRAFT_NOT_FOUND_MESSAGE)
    return draft


def serialize_draft(draft: AdvisoryDraft) -> dict:
    return {
        "id": draft.id,
        "customer_id": draft.customer_id,
        "advisor_id": draft.advisor_id,
        "tilt": draft.tilt,
        "content_classification": draft.content_classification,
        "candidates": draft.candidates,
        "allocation_suggestion": draft.allocation_suggestion,
        "warnings": draft.warnings,
        "profile_computed_at": draft.profile_computed_at.isoformat(),
        "candidate_pool_snapshot": draft.candidate_pool_snapshot,
        "generated_at": draft.generated_at.isoformat(),
        "advisory_request_id": draft.advisory_request_id,
        "disclaimer": disclaimer_for(draft.content_classification),
    }
