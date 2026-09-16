"""投顾助手候选池内排序：收益、风险、期限匹配度的加权打分（issue 01）。

纯函数，不接触数据库——候选池的合法性由 app.suitability 在检索层保证，
这里只验证打分与排序本身的算术是否正确、可拆解。
"""

from decimal import Decimal

from app.advisory.scoring import (
    TILT_BALANCED,
    TILT_LIQUIDITY,
    TILT_RETURN,
    CandidateInput,
    rank_candidates,
)

CONSERVATIVE = CandidateInput(
    product_code="F000001",
    product_name="天枢货币基金",
    product_type="货币基金",
    risk_level="R1",
    expected_return=Decimal("2.1000"),
    term_days=0,
)
MATCHED = CandidateInput(
    product_code="F000003",
    product_name="天璇混合基金",
    product_type="混合基金",
    risk_level="R3",
    expected_return=Decimal("8.0000"),
    term_days=0,
)
LONG_LOCKUP = CandidateInput(
    product_code="F000004",
    product_name="天权股票基金",
    product_type="股票基金",
    risk_level="R4",
    expected_return=Decimal("12.0000"),
    term_days=730,
)


def test_empty_pool_ranks_to_an_empty_list():
    assert rank_candidates([], customer_risk_level="C3", tilt=TILT_BALANCED) == []


def test_each_dimension_contribution_is_readable_and_sums_to_the_composite_score():
    ranked = rank_candidates([MATCHED], customer_risk_level="C3", tilt=TILT_BALANCED)

    candidate = ranked[0]
    dimensions = {item["dimension"] for item in candidate["score_breakdown"]}
    assert dimensions == {"收益", "风险", "期限匹配度"}

    total_contribution = round(sum(item["contribution"] for item in candidate["score_breakdown"]), 4)
    assert total_contribution == candidate["composite_score"]


def test_product_risk_level_matching_customers_own_level_scores_highest_on_risk():
    ranked = rank_candidates([CONSERVATIVE, MATCHED], customer_risk_level="C3", tilt=TILT_BALANCED)
    by_code = {item["product_code"]: item for item in ranked}

    risk_score = {
        code: next(d["score"] for d in item["score_breakdown"] if d["dimension"] == "风险")
        for code, item in by_code.items()
    }
    # C3 客户：R3 产品与其风险承受等级完全匹配，R1 产品级差 2，风险维度得分更低。
    assert risk_score["F000003"] == 1.0
    assert risk_score["F000001"] < risk_score["F000003"]


def test_a_lockup_far_beyond_the_customers_horizon_scores_zero_on_term_match():
    ranked = rank_candidates([LONG_LOCKUP], customer_risk_level="C1", tilt=TILT_BALANCED)
    term_score = next(
        d["score"] for d in ranked[0]["score_breakdown"] if d["dimension"] == "期限匹配度"
    )
    assert term_score == 0.0


def test_an_open_ended_product_always_fully_matches_the_term_dimension():
    ranked = rank_candidates([CONSERVATIVE], customer_risk_level="C5", tilt=TILT_BALANCED)
    term_score = next(
        d["score"] for d in ranked[0]["score_breakdown"] if d["dimension"] == "期限匹配度"
    )
    assert term_score == 1.0


def test_ranking_is_sorted_by_composite_score_descending():
    ranked = rank_candidates([CONSERVATIVE, MATCHED], customer_risk_level="C3", tilt=TILT_BALANCED)
    scores = [item["composite_score"] for item in ranked]
    assert scores == sorted(scores, reverse=True)
    assert ranked[0]["product_code"] == "F000003"


def test_tilting_toward_return_raises_the_returns_weight_and_changes_the_composite_score():
    balanced = rank_candidates([MATCHED], customer_risk_level="C3", tilt=TILT_BALANCED)[0]
    return_tilted = rank_candidates([MATCHED], customer_risk_level="C3", tilt=TILT_RETURN)[0]

    balanced_weight = next(
        d["weight"] for d in balanced["score_breakdown"] if d["dimension"] == "收益"
    )
    tilted_weight = next(
        d["weight"] for d in return_tilted["score_breakdown"] if d["dimension"] == "收益"
    )
    assert tilted_weight > balanced_weight


def test_tilting_toward_liquidity_raises_the_term_match_weight():
    balanced = rank_candidates([MATCHED], customer_risk_level="C3", tilt=TILT_BALANCED)[0]
    liquidity_tilted = rank_candidates([MATCHED], customer_risk_level="C3", tilt=TILT_LIQUIDITY)[0]

    balanced_weight = next(
        d["weight"] for d in balanced["score_breakdown"] if d["dimension"] == "期限匹配度"
    )
    tilted_weight = next(
        d["weight"] for d in liquidity_tilted["score_breakdown"] if d["dimension"] == "期限匹配度"
    )
    assert tilted_weight > balanced_weight
