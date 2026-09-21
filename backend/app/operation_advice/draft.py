"""操作建议的 AI 原稿落库与只读读取。

与方案的 AI 原稿同一条约束（`app.advisory.draft`）：只提供 record 与 get，没有
update——原稿落库后不可修改，是日后举证「审核是实质性的」的依据。

载荷只有「一个产品、一个方向、一个金额、一条理由」，赎回另带发起人选定的份额
（CONTEXT「操作建议」、ADR-0020、ADR-0021）：候选池快照、配置建议、画像警示都是
配置方案特有的，这里一个都不带（迁移 0026、0028）。
产品只存代码、不存名称——名称是 `fin_product` 的属性，存一份副本就会在改名时
留下两种口径，所以序列化时现查一次，产品不在目录里就少一个名字而不是整行消失
（待审队列对操作建议也是这个口径，见 `app.advisory.queue`）。
"""

from datetime import datetime
from decimal import Decimal
from typing import TypedDict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.classification import disclaimer_for
from app.db.models import OperationAdviceDraft, Product
from app.exceptions import AppError

DRAFT_NOT_FOUND_MESSAGE = "操作建议原稿不存在"


class DraftContent(TypedDict):
    """一条操作建议的全部内容——这些字段总是一起产生、一起落库，不单独存在。"""

    customer_id: int
    manager_id: int
    product_code: str
    direction: str
    amount: Decimal
    # 赎回时是发起人选定的份额，申购时为空。**为空表示「全部赎回」**：那是改动之前
    # 落库的行——当时只存金额，成交的是接受那一刻的全部持仓；新行一律带份额，
    # 别给新行写空值（那会把这条旧语义重新激活，而演示里看不出来）。
    redeemed_shares: Decimal | None
    reason: str
    content_classification: str
    generated_at: datetime


def record_draft(db: Session, content: DraftContent) -> OperationAdviceDraft:
    draft = OperationAdviceDraft(**content)
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


def get_draft(db: Session, draft_id: int) -> OperationAdviceDraft:
    draft = db.get(OperationAdviceDraft, draft_id)
    if draft is None:
        raise AppError(404, DRAFT_NOT_FOUND_MESSAGE)
    return draft


def serialize_draft(db: Session, draft: OperationAdviceDraft) -> dict:
    product_name = db.scalar(
        select(Product.product_name).where(Product.product_code == draft.product_code)
    )
    return {
        "id": draft.id,
        "customer_id": draft.customer_id,
        "manager_id": draft.manager_id,
        "product_code": draft.product_code,
        "product_name": product_name,
        "direction": draft.direction,
        "amount": format(draft.amount, "f"),
        "reason": draft.reason,
        "content_classification": draft.content_classification,
        "generated_at": draft.generated_at.isoformat(),
        "disclaimer": disclaimer_for(draft.content_classification),
    }
