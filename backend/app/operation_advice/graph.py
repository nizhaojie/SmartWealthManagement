"""业务操作 Agent：在候选池内为一位客户产出一条单笔操作建议（ADR-0017 的一份配置）。

与投顾助手共用同一套运行时与同一个审核中断（ADR-0007、ADR-0020），区别只在产物：
投顾助手出配置方案，这里出「一个产品、一个方向、一个金额、一条理由」。四件事在
结构上被钉住，不靠提示词自觉：

- **候选池是唯一的选品范围**：产品全部来自 `get_candidate_pool`，适当性硬过滤在那
  一层完成，这里不重新判断——越级产品根本进不了这个函数的输入（与投顾助手一致）。
- **不引入第二套排序**：选品复用 `app.advisory.scoring.rank_candidates`，「哪款产品
  更适合这位客户」在全系统只有一份判断，两个 Agent 不会各排各的。方向由客户经理
  选定的场景给出，因此这里始终用均衡权重，不提供第二套侧重。
- **金额由产品要素与持仓算出来**：申购取产品的起投金额（唯一由产品要素确定的金额），
  赎回取该持仓的成交金额；两个数都走 `app.order_acceptance` 的成交口径，不在这里
  另算一遍费率与净值——差一分钱，建议就成了当场会被拒绝的建议。
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
from app.advisory.scoring import TILT_BALANCED, CandidateInput, rank_candidates
from app.agent.config import OPERATION_ADVICE_CONFIG
from app.customer_assets.service import list_held_product_codes, list_holding_shares
from app.db.models import AdvisoryReview, Product
from app.exceptions import AppError
from app.funding_account.service import get_available_balance_value
from app.operation_advice.draft import DraftContent, record_draft
from app.operation_advice.reasons import purchase_reason, redemption_reason
from app.order_acceptance.service import (
    PURCHASE,
    REDEEM,
    purchase_cost,
    redemption_amount,
)
from app.suitability.service import get_candidate_pool

ALLOWED_DIRECTIONS = (PURCHASE, REDEEM)
UNKNOWN_DIRECTION_MESSAGE = "未知的操作方向"
NO_CANDIDATE_MESSAGE = "候选池内没有可申购的产品"
NOT_ENOUGH_BALANCE_MESSAGE = "可用余额不足以申购候选池内的任何产品"
NO_HOLDING_MESSAGE = "客户在候选池内没有可赎回的持仓"
ZERO = Decimal("0")


class OperationAdviceState(TypedDict, total=False):
    customer_id: int
    manager_id: int
    direction: str
    now: datetime
    thread_id: str
    candidate_pool: dict
    held_product_codes: set[str]
    holding_shares: dict[str, Decimal]
    available_balance: Decimal
    product: dict
    amount: Decimal
    redeemed_shares: Decimal
    reason: str
    draft_id: int
    review_outcome: dict
    result: dict


def _product_rows(db: Session, product_codes: list[str]) -> dict[str, Product]:
    """产品代码 → 产品行。金额、净值与费率都要用行上的字段，不是池里的摘要。"""
    rows = db.scalars(select(Product).where(Product.product_code.in_(product_codes))).all()
    return {row.product_code: row for row in rows}


def _ranked(state: OperationAdviceState, rows: dict[str, Product]) -> list[dict]:
    """在给定的产品行内排序——与投顾助手同一份排序（`app.advisory.scoring`）。"""
    return rank_candidates(
        [
            CandidateInput(
                product_code=row.product_code,
                product_name=row.product_name,
                product_type=row.product_type,
                risk_level=row.risk_level,
                expected_return=row.expected_return,
                term_days=row.term_days,
            )
            for row in rows.values()
        ],
        customer_risk_level=state["candidate_pool"]["customer_risk_level"],
        tilt=TILT_BALANCED,
    )


def _purchase_selection(db: Session, state: OperationAdviceState) -> tuple[dict, Decimal]:
    """申购：候选池内未持有的产品里排在最前、且买得起的那一只，金额取起投金额。

    「买得起」按受理侧的成交口径算（金额 + 手续费），因此这里给出的建议必然能被
    客户接受——生成一条当场会被拒绝的建议没有意义。
    """
    pool_codes = [item["product_code"] for item in state["candidate_pool"]["products"]]
    eligible = [code for code in pool_codes if code not in state["held_product_codes"]]
    if not eligible:
        raise AppError(400, NO_CANDIDATE_MESSAGE)

    rows = _product_rows(db, eligible)
    for candidate in _ranked(state, rows):
        row = rows.get(candidate["product_code"])
        if row is None:  # pragma: no cover - 候选池来自同一张表，必然存在
            continue
        if purchase_cost(row, row.min_amount) <= state["available_balance"]:
            return candidate, row.min_amount
    raise AppError(400, NOT_ENOUGH_BALANCE_MESSAGE)


def _redemption_selection(
    db: Session, state: OperationAdviceState
) -> tuple[dict, Decimal, Decimal]:
    """赎回：候选池内已持有的产品里得分最高的那一只（排序与申购是同一份）。

    产品仍需在候选池内——「生成的建议里产品全部来自候选池」是一条硬保证，赎回不
    例外。金额是该持仓的成交金额（份额 × 净值），方向是全部赎回。
    """
    held_in_pool = [
        item["product_code"]
        for item in state["candidate_pool"]["products"]
        if item["product_code"] in state["held_product_codes"]
        and state["holding_shares"].get(item["product_code"], ZERO) > ZERO
    ]
    if not held_in_pool:
        raise AppError(400, NO_HOLDING_MESSAGE)

    rows = _product_rows(db, held_in_pool)
    ranked = _ranked(state, rows)
    if not ranked:  # pragma: no cover - held_in_pool 非空且来自同一张表
        raise AppError(400, NO_HOLDING_MESSAGE)
    product = ranked[0]
    row = rows[product["product_code"]]
    shares = state["holding_shares"][product["product_code"]]
    return product, redemption_amount(row, shares), shares


def build_graph(db: Session, cache: redis.Redis):
    """编译这张图；必须用 `ADVISORY_CHECKPOINTER`——恢复时 `has_pending_checkpoint` 查的就是它。

    `cache` 是恢复运行时契约的一部分（`app.advisory.review` 以 `(db, cache)` 取图），
    本图不查检索与画像，因此用不到它。
    """
    graph = StateGraph(OperationAdviceState)

    def load_candidate_pool_node(state: OperationAdviceState) -> dict:
        pool = get_candidate_pool(db, customer_id=state["customer_id"], now=state["now"])
        return {
            "candidate_pool": pool,
            "held_product_codes": list_held_product_codes(db, customer_id=state["customer_id"]),
            "holding_shares": list_holding_shares(db, customer_id=state["customer_id"]),
        }

    def load_funding_account_node(state: OperationAdviceState) -> dict:
        return {
            "available_balance": get_available_balance_value(
                db, customer_id=state["customer_id"]
            )
        }

    def select_product_node(state: OperationAdviceState) -> dict:
        if state["direction"] == PURCHASE:
            product, amount = _purchase_selection(db, state)
            return {"product": product, "amount": amount}
        product, amount, shares = _redemption_selection(db, state)
        return {"product": product, "amount": amount, "redeemed_shares": shares}

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
