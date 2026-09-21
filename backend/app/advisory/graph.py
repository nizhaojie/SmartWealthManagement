"""投顾助手 Agent：候选池内排序 + 配置建议 + 审核中断（ADR-0007 的一份配置）。

打分排序到画像警示这一段是线性的确定性计算，不涉及模型调用——排序依据
必须能被稳定复现与逐项核对，交给模型判断只会引入它算错或编造引用的
风险。产出 AI 原稿后，图用运行时的 `interrupt()` 暂停，等待理财顾问在
审核流（app.advisory.review）里放行或驳回；暂停期间的状态由
app.advisory.runtime 的 checkpointer 承接，不是自己实现的状态机。
"""

from datetime import datetime, timedelta
from typing import TypedDict

import redis
from langgraph.graph import END, StateGraph
from langgraph.types import interrupt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import risk_focus
from app.advisory.allocation import suggest_allocation
from app.advisory.concentration import concentration_warnings
from app.advisory.draft import DraftContent, record_draft
from app.advisory.final import FinalContent, record_final
from app.advisory.pipeline import CONTENT_TYPE_PLAN, register_resume_graph
from app.advisory.reasons import build_reason
from app.advisory.review import record_decision
from app.advisory.review_status import ACTION_RELEASE, STATUS_PENDING
from app.advisory.runtime import ADVISORY_CHECKPOINTER
from app.advisory.scoring import TERM_HORIZON_DAYS, CandidateInput, rank_candidates
from app.advisory.warnings import (
    RISK_FOCUS_LOOKBACK_DAYS,
    profile_warnings,
    risk_focus_warnings,
)
from app.agent.config import ADVISORY_CONFIG
from app.customer_assets.look_through import portfolio_industry_exposure
from app.customer_assets.service import list_held_product_codes
from app.customer_profile.service import get_internal_profile
from app.db.models import AdvisoryReview, Product
from app.exceptions import AppError
from app.suitability.service import get_candidate_pool

REVIEW_MISSING_AT_RESUME_MESSAGE = "恢复审核时找不到对应的审核记录"


class AdvisoryState(TypedDict, total=False):
    customer_id: int
    advisor_id: int
    tilt: str
    now: datetime
    thread_id: str
    advisory_request_id: int | None
    profile: dict
    candidate_pool: dict
    held_product_codes: set[str]
    candidates: list[dict]
    allocation_suggestion: dict
    warnings: list[dict]
    draft_id: int
    review_outcome: dict
    result: dict


def _serialize_candidate(candidate: dict) -> dict:
    return {**candidate, "expected_return": format(candidate["expected_return"], "f")}


def _tag_lookup(profile: dict) -> dict:
    return {tag["key"]: tag["value"] for tag in profile["tags"]}


def build_graph(db: Session, cache: redis.Redis):
    graph = StateGraph(AdvisoryState)

    def load_profile_node(state: AdvisoryState) -> dict:
        profile = get_internal_profile(db, cache, customer_id=state["customer_id"], now=state["now"])
        return {"profile": profile}

    def load_candidate_pool_node(state: AdvisoryState) -> dict:
        pool = get_candidate_pool(db, customer_id=state["customer_id"], now=state["now"])
        held = list_held_product_codes(db, customer_id=state["customer_id"])
        return {"candidate_pool": pool, "held_product_codes": held}

    def score_candidates_node(state: AdvisoryState) -> dict:
        pool = state["candidate_pool"]
        eligible_codes = [
            item["product_code"]
            for item in pool["products"]
            if item["product_code"] not in state["held_product_codes"]
        ]
        if not eligible_codes:
            return {"candidates": []}

        rows = db.scalars(select(Product).where(Product.product_code.in_(eligible_codes))).all()
        records = [
            CandidateInput(
                product_code=row.product_code,
                product_name=row.product_name,
                product_type=row.product_type,
                risk_level=row.risk_level,
                expected_return=row.expected_return,
                term_days=row.term_days,
            )
            for row in rows
        ]
        ranked = rank_candidates(
            records,
            customer_risk_level=pool["customer_risk_level"],
            tilt=state["tilt"],
        )
        return {"candidates": ranked}

    def build_reasons_node(state: AdvisoryState) -> dict:
        customer_risk_level = state["candidate_pool"]["customer_risk_level"]
        horizon_days = TERM_HORIZON_DAYS[customer_risk_level]
        tags = _tag_lookup(state["profile"])
        product_preference = tags.get("product_preference", {}) or {}
        investment_experience = tags.get("investment_experience")
        candidates = [
            {
                **candidate,
                "reason": build_reason(
                    candidate,
                    customer_risk_level=customer_risk_level,
                    product_preference=product_preference,
                    horizon_days=horizon_days,
                    investment_experience=investment_experience,
                ),
            }
            for candidate in state["candidates"]
        ]
        return {"candidates": candidates}

    def suggest_allocation_node(state: AdvisoryState) -> dict:
        target_allocation = _tag_lookup(state["profile"]).get("target_allocation", {}) or {}
        return {"allocation_suggestion": suggest_allocation(target_allocation, state["tilt"])}

    def collect_warnings_node(state: AdvisoryState) -> dict:
        profile = state["profile"]
        computed_at = datetime.fromisoformat(profile["computed_at"])
        found = profile_warnings(tags=profile["tags"], computed_at=computed_at, now=state["now"])
        exposure = portfolio_industry_exposure(db, customer_id=state["customer_id"])
        found = found + concentration_warnings(exposure)
        # 风控预警带来的风险标记：订阅方在广播到达时写下的关注记录，这里只读。
        # 广播漏了就是少一条提示，方案照常生成——协作是增强，不是前置条件。
        focuses = [
            risk_focus.focus_facts(row)
            for row in risk_focus.recent_for_customer(
                db,
                customer_id=state["customer_id"],
                focus_type=risk_focus.FOCUS_RISK_ALERT,
                since=state["now"] - timedelta(days=RISK_FOCUS_LOOKBACK_DAYS),
            )
        ]
        found = found + risk_focus_warnings(focuses)
        return {"warnings": found}

    def persist_draft_node(state: AdvisoryState) -> dict:
        draft = record_draft(
            db,
            DraftContent(
                customer_id=state["customer_id"],
                advisor_id=state["advisor_id"],
                tilt=state["tilt"],
                content_classification=ADVISORY_CONFIG.content_classification_default,
                candidates=[_serialize_candidate(c) for c in state["candidates"]],
                allocation_suggestion=state["allocation_suggestion"],
                warnings=state["warnings"],
                profile_computed_at=datetime.fromisoformat(state["profile"]["computed_at"]),
                candidate_pool_snapshot=state["candidate_pool"],
                generated_at=state["now"],
                advisory_request_id=state.get("advisory_request_id"),
            ),
        )
        db.add(
            AdvisoryReview(
                # 审核记录是所有投顾内容共用的，所以这里要标明这是哪一类内容、
                # 内容在哪：方案的载荷就是这份 AI 原稿，两个标识因此指向同一个 id。
                content_type=CONTENT_TYPE_PLAN,
                content_ref=draft.id,
                draft_id=draft.id,
                thread_id=state["thread_id"],
                status=STATUS_PENDING,
            )
        )
        db.commit()
        return {"draft_id": draft.id}

    def await_review_node(state: AdvisoryState) -> dict:
        # 暂停发生在这里：第一次跑到这个节点时 interrupt() 会中断整张图，
        # 状态由 app.advisory.runtime 的 checkpointer 承接。理财顾问放行或
        # 驳回时，app.advisory.review 用同一个 thread_id 以
        # Command(resume=...) 续跑——这个节点会从头重新执行一次，这次
        # interrupt() 直接返回续跑时带的决定，不再暂停。
        outcome = interrupt({"draft_id": state["draft_id"], "customer_id": state["customer_id"]})
        return {"review_outcome": outcome}

    def finalize_node(state: AdvisoryState) -> dict:
        outcome = state["review_outcome"]
        review = db.scalar(
            select(AdvisoryReview).where(AdvisoryReview.draft_id == state["draft_id"])
        )
        if review is None:
            # persist_draft 已经在同一次运行里建过这条审核记录，恢复时它
            # 必然还在——真出现 None 说明有别的代码路径删掉了它。
            raise AppError(500, REVIEW_MISSING_AT_RESUME_MESSAGE)

        if outcome["action"] == ACTION_RELEASE:
            final = record_final(
                db,
                FinalContent(
                    draft_id=state["draft_id"],
                    customer_id=state["customer_id"],
                    advisor_id=outcome["advisor_id"],
                    content_classification=ADVISORY_CONFIG.content_classification_default,
                    candidates=outcome["candidates"],
                    allocation_suggestion=outcome["allocation_suggestion"],
                    warnings=outcome["warnings"],
                    released_at=outcome["now"],
                ),
            )
            record_decision(
                db,
                review=review,
                action=outcome["action"],
                advisor_id=outcome["advisor_id"],
                reason=None,
                now=outcome["now"],
            )
            return {"result": {"final_id": final.id}}

        record_decision(
            db,
            review=review,
            action=outcome["action"],
            advisor_id=outcome["advisor_id"],
            reason=outcome["reason"],
            now=outcome["now"],
        )
        return {"result": {"rejected": True}}

    graph.add_node("load_profile", load_profile_node)
    graph.add_node("load_candidate_pool", load_candidate_pool_node)
    graph.add_node("score_candidates", score_candidates_node)
    graph.add_node("build_reasons", build_reasons_node)
    graph.add_node("suggest_allocation", suggest_allocation_node)
    graph.add_node("collect_warnings", collect_warnings_node)
    graph.add_node("persist_draft", persist_draft_node)
    graph.add_node("await_review", await_review_node)
    graph.add_node("finalize", finalize_node)

    graph.set_entry_point("load_profile")
    graph.add_edge("load_profile", "load_candidate_pool")
    graph.add_edge("load_candidate_pool", "score_candidates")
    graph.add_edge("score_candidates", "build_reasons")
    graph.add_edge("build_reasons", "suggest_allocation")
    graph.add_edge("suggest_allocation", "collect_warnings")
    graph.add_edge("collect_warnings", "persist_draft")
    graph.add_edge("persist_draft", "await_review")
    graph.add_edge("await_review", "finalize")
    graph.add_edge("finalize", END)

    return graph.compile(checkpointer=ADVISORY_CHECKPOINTER)


# 这张图是「方案」这一类内容的恢复运行时：审核记录上的 thread_id 指向它的一次运行，
# 放行/驳回时由 app.advisory.review 按内容类型查表拿到它（见 app.advisory.pipeline）。
register_resume_graph(CONTENT_TYPE_PLAN, build_graph)
