"""业务操作 Agent：就发起人选定的产品与金额 / 份额，为一位客户产出单笔操作建议的理由
（ADR-0017 的一份配置，输入口径见 ADR-0021）。

与投顾助手共用同一套运行时与同一个审核中断（ADR-0007、ADR-0020），区别只在产物：
投顾助手出配置方案，这里出「一个产品、一个方向、一个金额、一条理由」。四件事在
结构上被钉住，不靠提示词自觉：

- **产品与金额 / 份额由发起人选定，这张图不裁量**（ADR-0021）：三个输入在受理处
  校验通过之后才进图（`app.operation_advice.service` 调 `options` 的同一份计算），
  这里只按代码加载产品、采用给定的那个数。图里因此没有排序、没有选品——「谁选的」
  在代码里一眼可见。
- **候选池仍是唯一的产品范围**：受理校验读的可选项就是「候选池 − 已持有」（申购）
  与「候选池 ∩ 已持有」（赎回），适当性硬过滤仍在那一条链上，这里不重新判断。
- **理由只引用事实**：产品要素与客户自己的持仓 / 余额（`app.operation_advice.reasons`）。
- **一次只有一个产品一个方向**：载荷表上产品与方向各是一列、金额非空且大于零
  （迁移 0026），这一层产不出第二条建议。

产出 AI 原稿后图用运行时的 `interrupt()` 暂停，等理财顾问放行或驳回；暂停期间的
状态由 `app.advisory.runtime` 的 checkpointer 承接（与投顾助手是同一个实例，
`has_pending_checkpoint` 查的就是它）。
"""

from datetime import datetime
from decimal import Decimal
from typing import TypedDict

import redis
from langgraph.graph import END, StateGraph
from langgraph.types import interrupt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.advisory.pipeline import CONTENT_TYPE_OPERATION_ADVICE, register_resume_graph
from app.advisory.review import get_review_by_content, record_decision
from app.advisory.review_status import ACTION_RELEASE, STATUS_PENDING
from app.advisory.runtime import ADVISORY_CHECKPOINTER
from app.agent.config import OPERATION_ADVICE_CONFIG
from app.customer_assets.service import list_holding_shares
from app.db.models import AdvisoryReview, Product
from app.exceptions import AppError
from app.funding_account.service import get_available_balance_value
from app.operation_advice.draft import DraftContent, record_draft
from app.operation_advice.options import not_in_options_message, product_elements
from app.operation_advice.reasons import purchase_reason, redemption_reason
from app.order_acceptance.service import PURCHASE, redemption_amount
from app.suitability.service import get_candidate_pool


class OperationAdviceState(TypedDict, total=False):
    customer_id: int
    manager_id: int
    direction: str
    now: datetime
    thread_id: str
    # 发起人选定、且已被受理校验放行的输入：产品代码，以及金额（申购）/ 份额（赎回）
    # 二选一。它们进图时就已经是确定值，图不再改动它们。
    product_code: str
    amount: Decimal
    shares: Decimal
    candidate_pool: dict
    available_balance: Decimal
    product: dict
    redeemed_shares: Decimal
    # 客户的持仓份额（赎回的理由要写「从多少份里赎回多少份」，与发起人给的份额是两个数）。
    held_shares: Decimal
    reason: str
    draft_id: int
    review_outcome: dict
    result: dict


def _product_row(db: Session, state: OperationAdviceState) -> Product:
    """按发起人给的代码加载产品行：净值（赎回的成交金额）与产品要素都在行上。

    **这不是一次范围检查**——产品在不在该方向的可选项里，受理处已经判定过
    （`app.operation_advice.options`）。走到这里还是查不到，只可能是目录在读池与
    读行之间变了，按受理校验的同一套文案拒绝，而不是给出一条凭空的建议。
    """
    row = db.scalar(
        select(Product).where(Product.product_code == state["product_code"])
    )
    if row is None:  # pragma: no cover - 受理校验刚在可选项里找到过它
        raise AppError(400, not_in_options_message(state["direction"]))
    return row


def build_graph(db: Session, cache: redis.Redis):
    """编译这张图；必须用 `ADVISORY_CHECKPOINTER`——恢复时 `has_pending_checkpoint` 查的就是它。

    `cache` 是恢复运行时契约的一部分（`app.advisory.review` 以 `(db, cache)` 取图），
    本图不查检索与画像，因此用不到它。
    """
    graph = StateGraph(OperationAdviceState)

    def load_candidate_pool_node(state: OperationAdviceState) -> dict:
        # 这一层只剩一个用途：理由要引用的客户风险承受等级。产品范围不在这里判断——
        # 发起人选的产品的受理校验已经跑过，仍要读池只因为理由的措辞要写它。
        pool = get_candidate_pool(db, customer_id=state["customer_id"], now=state["now"])
        return {"candidate_pool": pool}

    def load_funding_account_node(state: OperationAdviceState) -> dict:
        # 同上：申购理由要写「这次金额在可用余额之内」，那个数是客户自己的事实。
        return {
            "available_balance": get_available_balance_value(
                db, customer_id=state["customer_id"]
            )
        }

    def select_product_node(state: OperationAdviceState) -> dict:
        """按发起人给的代码加载产品，采用给定的金额或份额——这里不选品、不排序。

        申购采用的金额就是发起人填的那个数；赎回给出的是份额，成交金额由它算出来
        （份额 × 净值，与受理侧同一个 `redemption_amount`），两个数一起落进草案。
        赎回还要读一次客户当前的持仓份额：理由要写「从多少份里赎回多少份」，那是
        客户自己的事实，与发起人填的份额不是同一个数（部分赎回时两者不相等）。
        """
        row = _product_row(db, state)
        if state["direction"] == PURCHASE:
            return {"product": product_elements(row), "amount": state["amount"]}
        shares = state["shares"]
        return {
            "product": product_elements(row),
            "amount": redemption_amount(row, shares),
            "redeemed_shares": shares,
            "held_shares": list_holding_shares(db, customer_id=state["customer_id"]).get(
                state["product_code"], Decimal("0")
            ),
        }

    def build_reason_node(state: OperationAdviceState) -> dict:
        if state["direction"] == PURCHASE:
            reason = purchase_reason(
                product=state["product"],
                customer_risk_level=state["candidate_pool"]["customer_risk_level"],
                amount=state["amount"],
                available_balance=state["available_balance"],
            )
        else:
            reason = redemption_reason(
                product=state["product"],
                held_shares=state["held_shares"],
                shares=state["redeemed_shares"],
                amount=state["amount"],
            )
        return {"reason": reason}

    def persist_draft_node(state: OperationAdviceState) -> dict:
        draft = record_draft(
            db,
            DraftContent(
                customer_id=state["customer_id"],
                manager_id=state["manager_id"],
                product_code=state["product"]["product_code"],
                direction=state["direction"],
                amount=state["amount"],
                # 赎回写上发起人选定的份额——「赎回多少」从此在生成时就定下来；
                # 这一列为空只服务改动之前落库的行（那时成交的是当下的全部持仓），
                # 申购方向没有这一项。
                redeemed_shares=state.get("redeemed_shares"),
                reason=state["reason"],
                content_classification=OPERATION_ADVICE_CONFIG.content_classification_default,
                generated_at=state["now"],
            ),
        )
        db.add(
            AdvisoryReview(
                # 审核记录是所有投顾内容共用的（ADR-0020）：这里标明这是操作建议、
                # 内容在哪。`draft_id` 是方案特有的列，操作建议不写它。
                content_type=CONTENT_TYPE_OPERATION_ADVICE,
                content_ref=draft.id,
                thread_id=state["thread_id"],
                status=STATUS_PENDING,
            )
        )
        db.commit()
        return {"draft_id": draft.id}

    def await_review_node(state: OperationAdviceState) -> dict:
        # 暂停发生在这里：第一次跑到这个节点时 interrupt() 中断整张图，状态由
        # app.advisory.runtime 的 checkpointer 承接。理财顾问放行或驳回时，
        # app.advisory.review 用同一个 thread_id 以 Command(resume=...) 续跑。
        outcome = interrupt({"draft_id": state["draft_id"], "customer_id": state["customer_id"]})
        return {"review_outcome": outcome}

    def finalize_node(state: OperationAdviceState) -> dict:
        outcome = state["review_outcome"]
        review = get_review_by_content(
            db, content_type=CONTENT_TYPE_OPERATION_ADVICE, content_ref=state["draft_id"]
        )
        # 放行不产生第二份载荷：操作建议的原稿落库后不可修改，顾问放行的就是这一份
        # （没有可编辑的字段），「已放行」这个状态本身就是送达依据。
        record_decision(
            db,
            review=review,
            action=outcome["action"],
            advisor_id=outcome["advisor_id"],
            reason=outcome.get("reason"),
            now=outcome["now"],
        )
        return {"result": {"draft_id": state["draft_id"], "status": review.status}}

    graph.add_node("load_candidate_pool", load_candidate_pool_node)
    graph.add_node("load_funding_account", load_funding_account_node)
    graph.add_node("select_product", select_product_node)
    graph.add_node("build_reason", build_reason_node)
    graph.add_node("persist_draft", persist_draft_node)
    graph.add_node("await_review", await_review_node)
    graph.add_node("finalize", finalize_node)

    graph.set_entry_point("load_candidate_pool")
    graph.add_edge("load_candidate_pool", "load_funding_account")
    graph.add_edge("load_funding_account", "select_product")
    graph.add_edge("select_product", "build_reason")
    graph.add_edge("build_reason", "persist_draft")
    graph.add_edge("persist_draft", "await_review")
    graph.add_edge("await_review", "finalize")
    graph.add_edge("finalize", END)

    return graph.compile(checkpointer=ADVISORY_CHECKPOINTER)


# 这张图是「操作建议」这一类内容的恢复运行时：审核记录上的 thread_id 指向它的一次
# 运行，放行/驳回时由 app.advisory.review 按内容类型查表拿到它（app.advisory.pipeline）。
# 必须用同一个 ADVISORY_CHECKPOINTER 编译——`has_pending_checkpoint` 查的就是它。
register_resume_graph(CONTENT_TYPE_OPERATION_ADVICE, build_graph)
