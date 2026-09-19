"""顾问定稿的落库与只读读取。

同 app.advisory.draft 一样，只提供 record 与 get，没有 update——定稿落库
后不可修改，它与 AI 原稿并存，两者的差异是举证「审核是实质性的」的
依据。定稿是唯一允许经客户侧接口读取的版本。

定稿同时供两端读取，但两端要的东西不一样：内部端要完整的举证材料
（`serialize_final`），客户侧只要**客户送达视图**（`serialize_final_for_customer`）。
裁剪发生在服务端，不共用内部端的序列化（见 ADR-0016）。
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
    # 排序口径与 list_finals_for_customer 一致：都是「最新一份」的另一个
    # 出口，两处口径分叉会让客户在列表首行与「最新一份」之间看到不同的
    # 方案。released_at 相同时用 id 兜底，结果才是确定的。
    final = db.scalar(
        select(AdvisoryFinal)
        .where(AdvisoryFinal.customer_id == customer_id)
        .order_by(AdvisoryFinal.released_at.desc(), AdvisoryFinal.id.desc())
    )
    if final is None:
        raise AppError(404, FINAL_NOT_FOUND_MESSAGE)
    return final


def list_finals_for_customer(db: Session, *, customer_id: int) -> list[AdvisoryFinal]:
    return list(
        db.scalars(
            select(AdvisoryFinal)
            .where(AdvisoryFinal.customer_id == customer_id)
            .order_by(AdvisoryFinal.released_at.desc(), AdvisoryFinal.id.desc())
        ).all()
    )


def get_final_for_customer_by_id(db: Session, *, final_id: int, customer_id: int) -> AdvisoryFinal:
    """按 id 取一份定稿，但只在这份定稿属于该客户时才给。

    这个接口不像 `get_latest_final_for_customer` 那样天然被令牌圈定范围，
    越权检查必须显式写在查询条件里：id 不属于调用者时与不存在一样，回
    404 而不是 403——不确认他人资源是否存在。
    """
    final = db.scalar(
        select(AdvisoryFinal).where(
            AdvisoryFinal.id == final_id,
            AdvisoryFinal.customer_id == customer_id,
        )
    )
    if final is None:
        raise AppError(404, FINAL_NOT_FOUND_MESSAGE)
    return final


# 客户送达视图里产品清单保留的字段：客观已披露的产品要素。综合得分、
# 排序依据与推荐理由都不在其中（见 ADR-0016），因此这里逐项拣选，不用
# `{**candidate}` 展开——以后往候选里加字段时默认是内部字段，要让它送达
# 客户必须在这里显式加一次。
CUSTOMER_VISIBLE_PRODUCT_FIELDS = (
    "product_code",
    "product_name",
    "product_type",
    "risk_level",
    "expected_return",
    "term_days",
)


def _serialize_candidate_for_customer(candidate: dict) -> dict:
    return {field: candidate.get(field) for field in CUSTOMER_VISIBLE_PRODUCT_FIELDS}


def _advisor_name(db: Session, final: AdvisoryFinal) -> str | None:
    """两端都要「方案由哪位顾问出具」，这段查询不因裁剪而分叉。"""
    advisor = db.get(Employee, final.advisor_id)
    return advisor.real_name if advisor else None


def serialize_final_for_customer(db: Session, final: AdvisoryFinal) -> dict:
    return {
        "id": final.id,
        "advisor_name": _advisor_name(db, final),
        "candidates": [_serialize_candidate_for_customer(c) for c in final.candidates],
        "allocation_suggestion": final.allocation_suggestion,
        "released_at": final.released_at.isoformat(),
        "disclaimer": disclaimer_for(final.content_classification),
    }


def serialize_final(db: Session, final: AdvisoryFinal) -> dict:
    # 客户要知道方案是谁出具的才能找得到人（见客户故事「看到方案由哪位
    # 顾问出具」），所以定稿在这里带出顾问姓名，不只是一个内部的 advisor_id。
    return {
        "id": final.id,
        "draft_id": final.draft_id,
        "customer_id": final.customer_id,
        "advisor_id": final.advisor_id,
        "advisor_name": _advisor_name(db, final),
        "content_classification": final.content_classification,
        "candidates": final.candidates,
        "allocation_suggestion": final.allocation_suggestion,
        "warnings": final.warnings,
        "released_at": final.released_at.isoformat(),
        "disclaimer": disclaimer_for(final.content_classification),
    }
