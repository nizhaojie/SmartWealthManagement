"""投顾助手 Agent：候选池内排序 + 配置建议（ADR-0007 的一份配置）。

链路是线性的：读画像、读候选池（顺带排除已持有产品）、打分排序、
写理由、配置建议、画像警示。除候选池读取会落一条适当性判定记录外，
全程是确定性计算，不涉及模型调用——排序依据必须能被稳定复现与逐项
核对，交给模型判断只会引入它算错或编造引用的风险。
"""

from datetime import datetime
from typing import TypedDict

import redis
from langgraph.graph import END, StateGraph
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.advisory.allocation import suggest_allocation
from app.advisory.reasons import build_reason
from app.advisory.scoring import TERM_HORIZON_DAYS, CandidateInput, rank_candidates
from app.advisory.warnings import profile_warnings
from app.customer_assets.service import list_held_product_codes
from app.customer_profile.service import get_internal_profile
from app.db.models import Product
from app.suitability.service import get_candidate_pool


class AdvisoryState(TypedDict, total=False):
    customer_id: int
    tilt: str
    now: datetime
    profile: dict
    candidate_pool: dict
    held_product_codes: set[str]
    candidates: list[dict]
    allocation_suggestion: dict
    warnings: list[dict]


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
        return {"warnings": found}

    graph.add_node("load_profile", load_profile_node)
    graph.add_node("load_candidate_pool", load_candidate_pool_node)
    graph.add_node("score_candidates", score_candidates_node)
    graph.add_node("build_reasons", build_reasons_node)
    graph.add_node("suggest_allocation", suggest_allocation_node)
    graph.add_node("collect_warnings", collect_warnings_node)

    graph.set_entry_point("load_profile")
    graph.add_edge("load_profile", "load_candidate_pool")
    graph.add_edge("load_candidate_pool", "score_candidates")
    graph.add_edge("score_candidates", "build_reasons")
    graph.add_edge("build_reasons", "suggest_allocation")
    graph.add_edge("suggest_allocation", "collect_warnings")
    graph.add_edge("collect_warnings", END)

    return graph.compile()
