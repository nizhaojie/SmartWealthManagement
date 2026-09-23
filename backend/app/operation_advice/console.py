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

进度表是一个分页列表（ADR-0024）：`total` 由同一条查询派生（`count_matching`），
不是另数一遍本页——客户经理看到「共 N 条」却只能翻到少数几条时，两个数字看起来
都是真的，谁也不报错。
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.advisory.pipeline import CONTENT_TYPE_OPERATION_ADVICE
from app.db.models import AdvisoryReview, OperationAdviceDraft
from app.operation_advice.decision import (
    decisions_by_advice,
    optional_release_moment,
    product_names,
    released_at_by_review,
    status_of,
)
from app.pagination import PageParams, count_matching, paginated_response

# 进度的先后口径，只有这一处：最近发起的在前，同一秒发起的用建议标识兜底。
# 兜底键不是修辞——`generated_at` 只到秒，同一秒落库的两条若没有确定的先后，翻页
# 会把一条读两次、另一条谁也读不到，而两页看起来都正常（ADR-0024）。
LATEST_FIRST = (OperationAdviceDraft.generated_at.desc(), OperationAdviceDraft.id.desc())


def serialize_review_status(review: AdvisoryReview) -> dict:
    """审核状态。方案的对应响应按原稿 id 寻址，操作建议按建议自己的 id。

    不返回 `draft_id`：那是方案特有的列，操作建议上它永远是空——回一个恒为 null 的
    字段，只会让前端以为存在一个可以点开的东西。
    """
    return {"advice_id": review.content_ref, "status": review.status}


def list_for_customer(
    db: Session, *, customer_id: int, now: datetime, page: PageParams
) -> dict:
    """某位客户已发起的建议与它们的进度的一页（最近发起的在前），以及过滤后总数。

    可见范围按**客户归属**判定（调用点先过 `ensure_can_view`，与审核队列、预警列表
    同一个口径），不按发起人：客户转手之后，新经理要看得见这位客户身上发生的一切，
    包括上一任发起的建议——按发起人过滤会让他看到一个不像真的账户。

    「还没有建议」是空列表，不是 404——它不是一种错误，客户经理要看到的是「我还没
    为他发起过」。分页之后这一句只对 `total === 0` 成立：越界的那一页也可以是空的。
    """
    statement = (
        select(AdvisoryReview, OperationAdviceDraft)
        .join(OperationAdviceDraft, OperationAdviceDraft.id == AdvisoryReview.content_ref)
        .where(
            AdvisoryReview.content_type == CONTENT_TYPE_OPERATION_ADVICE,
            OperationAdviceDraft.customer_id == customer_id,
        )
        .order_by(*LATEST_FIRST)
    )
    total = count_matching(db, statement)
    rows = db.execute(
        statement.offset(page.offset).limit(page.page_size)
    ).all()

    advice_ids = [draft.id for _review, draft in rows]
    decisions = decisions_by_advice(db, advice_ids)
    released = released_at_by_review(db, [review.id for review, _draft in rows])
    names = product_names(db, {draft.product_code for _review, draft in rows})

    items = []
    for review, draft in rows:
        # 放行留痕与「已放行必有留痕」这条规则都只有一处（`decision.optional_release_moment`）：
        # 客户侧读的是同一份事实，两处各写一遍迟早会分叉，而分叉的那一份看起来仍然正常。
        moment = optional_release_moment(review, released)
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
    return paginated_response(items, total=total, params=page)
