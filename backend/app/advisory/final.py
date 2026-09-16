"""顾问定稿的落库与只读读取。

同 app.advisory.draft 一样，只提供 record 与 get，没有 update——定稿落库
后不可修改，它与 AI 原稿并存，两者的差异是举证「审核是实质性的」的
依据。定稿是唯一允许经客户侧接口读取的版本。
"""

from datetime import datetime
from typing import TypedDict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.classification import disclaimer_for
from app.db.models import AdvisoryFinal, Employee
from app.exceptions import AppError

FINAL_NOT_FOUND_MESSAGE = "尚无已放行的方案"


class FinalContent(TypedDict):
    draft_id: int
    customer_id: int
    advisor_id: int
    content_classification: str
    candidates: list[dict]
    allocation_suggestion: dict
    warnings: list[dict]
    released_at: datetime


def record_final(db: Session, content: FinalContent) -> AdvisoryFinal:
    final = AdvisoryFinal(**content)
    db.add(final)
    db.commit()
    db.refresh(final)
    return final


def get_final_by_draft_id(db: Session, draft_id: int) -> AdvisoryFinal:
    final = db.scalar(select(AdvisoryFinal).where(AdvisoryFinal.draft_id == draft_id))
    if final is None:
        raise AppError(404, FINAL_NOT_FOUND_MESSAGE)
    return final


def get_latest_final_for_customer(db: Session, *, customer_id: int) -> AdvisoryFinal:
    final = db.scalar(
        select(AdvisoryFinal)
        .where(AdvisoryFinal.customer_id == customer_id)
        .order_by(AdvisoryFinal.id.desc())
    )
    if final is None:
        raise AppError(404, FINAL_NOT_FOUND_MESSAGE)
    return final


def serialize_final(db: Session, final: AdvisoryFinal) -> dict:
    # 客户要知道方案是谁出具的才能找得到人（见客户故事「看到方案由哪位
    # 顾问出具」），所以定稿在这里带出顾问姓名，不只是一个内部的 advisor_id。
    advisor = db.get(Employee, final.advisor_id)
    return {
        "id": final.id,
        "draft_id": final.draft_id,
        "customer_id": final.customer_id,
        "advisor_id": final.advisor_id,
        "advisor_name": advisor.real_name if advisor else None,
        "content_classification": final.content_classification,
        "candidates": final.candidates,
        "allocation_suggestion": final.allocation_suggestion,
        "warnings": final.warnings,
        "released_at": final.released_at.isoformat(),
        "disclaimer": disclaimer_for(final.content_classification),
    }
