"""操作建议的内部读取：审核页要看的载荷、审核状态，与客户经理要看的进度。

两类投顾内容共用一条审核流水线（ADR-0020），所以这一层只补「操作建议那一侧怎么读」，
不另写一套加锁、恢复或留言：留言仍按审核记录寻址（`app.advisory.comments`），与内容
类型无关；放行与驳回仍走 `app.operation_advice.review`。

**进度是两个口径，都是事实陈述，都不落库**（`app.operation_advice.decision` 已经立过
这条规矩）：

- **审核进度**来自审核记录：待审 / 处理中 / 已放行 / 已驳回；
- **客户决定**只在已放行之后才有：待客户决定 / 已接受 / 已拒绝 / 已过期。

两个口径都要，是因为它们回答的不是同一个问题：客户经理问「顾问看了没有」，顾问放行
之后问的是「客户答了没有」。合成一个字段会丢掉其中一半，而丢掉的那一半正是他要的。

**载荷逐字段来自 `app.operation_advice.draft.serialize_draft`**，不在这里再拼一遍：
它已经是「一个产品、一个方向、一个金额、一条理由」，抄一份出来就会在加字段时漂移，
而漂移的那一份看起来仍然是完整的。
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.advisory.pipeline import CONTENT_TYPE_OPERATION_ADVICE
from app.advisory.review_status import STATUS_RELEASED
from app.db.models import AdvisoryReview, OperationAdviceDraft
from app.exceptions import AppError
from app.operation_advice.decision import (
    MISSING_RELEASED_AT_MESSAGE,
    decisions_by_advice,
    product_names,
    released_at_by_review,
    status_of,
)


def serialize_review_status(review: AdvisoryReview) -> dict:
    """审核状态。方案的对应响应按原稿 id 寻址，操作建议按建议自己的 id。

    不返回 `draft_id`：那是方案特有的列，操作建议上它永远是空——回一个恒为 null 的
    字段，只会让前端以为存在一个可以点开的东西。
    """
    return {"advice_id": review.content_ref, "status": review.status}


def list_for_customer(db: Session, *, customer_id: int, now: datetime) -> dict:
    """某位客户已发起的建议与它们的进度，最近发起的在前。

    可见范围按**客户归属**判定（调用点先过 `ensure_can_view`，与审核队列、预警列表
    同一个口径），不按发起人：客户转手之后，新经理要看得见这位客户身上发生的一切，
    包括上一任发起的建议——按发起人过滤会让他看到一个不像真的账户。

    「还没有建议」是空列表，不是 404——它不是一种错误，客户经理要看到的是「我还没
    为他发起过」。
    """
    rows = db.execute(
        select(AdvisoryReview, OperationAdviceDraft)
        .join(OperationAdviceDraft, OperationAdviceDraft.id == AdvisoryReview.content_ref)
        .where(
            AdvisoryReview.content_type == CONTENT_TYPE_OPERATION_ADVICE,
            OperationAdviceDraft.customer_id == customer_id,
        )
        .order_by(
            OperationAdviceDraft.generated_at.desc(), OperationAdviceDraft.id.desc()
        )
    ).all()

    advice_ids = [draft.id for _review, draft in rows]
    decisions = decisions_by_advice(db, advice_ids)
    released = released_at_by_review(db, [review.id for review, _draft in rows])
    names = product_names(db, {draft.product_code for _review, draft in rows})

    items = []
    for review, draft in rows:
        moment = released.get(review.id)
        if review.status == STATUS_RELEASED and moment is None:
            # 已放行却没有放行留痕：与客户侧同一条口径（`record_decision` 一次提交里
            # 同时写两者），宁可当场报错，也不要把一条读不出进度的建议说成没放行过。
            raise AppError(500, MISSING_RELEASED_AT_MESSAGE)
        decision = decisions.get(draft.id)
        items.append(
            {
                "id": draft.id,
                "product_code": draft.product_code,
                "product_name": names.get(draft.product_code),
                "direction": draft.direction,
                "amount": format(draft.amount, "f"),
                "reason": draft.reason,
                "review_status": review.status,
                # 未放行时客户侧还没有这条建议，「待客户决定」无从谈起，因此是空。
                "customer_status": (
                    status_of(
                        decision=decision.decision if decision is not None else None,
                        released_at=moment,
                        now=now,
                    )
                    if moment is not None
                    else None
                ),
                "generated_at": draft.generated_at.isoformat(),
            }
        )
    return {"advice": items}
