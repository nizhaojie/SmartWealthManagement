"""综合重排（五因子、按场景配置权重）作为纯函数直接测输入输出。

三件事在这里被钉住：

- 权重按场景配置、不同场景排出的先后不同；
- 输出是**排序不是过滤**，低分单元排在后面但仍然在结果里；
- 时间基准显式传入（ADR-0011），「基准为某时刻时谁排在前面」是一个纯计算。
"""

from datetime import datetime, timedelta

import pytest

from app.customer_profile.rerank import (
    DEFAULT_SCENARIO_WEIGHTS,
    FACTOR_BASE_CONFIDENCE,
    FACTOR_CONFLICT_PENALTY,
    FACTOR_HISTORICAL_ACCURACY,
    FACTOR_RECENCY,
    FACTOR_SEMANTIC_SIMILARITY,
    SCENARIO_CUSTOMER_SERVICE,
    SCENARIO_PRODUCT_RECOMMENDATION,
    SCENARIO_PROFILE_REVIEW,
    SCENARIO_RISK_ANALYSIS,
    UNKNOWN_SCENARIO_MESSAGE,
    MemoryUnit,
    recency,
    rerank,
    weights_for_scenario,
)

NOW = datetime(2026, 9, 17, 12, 0, 0)


def _unit(
    key: str,
    *,
    similarity: float = 0.5,
    observed_at: datetime = NOW,
    accuracy: float = 0.5,
    base: float = 0.5,
    conflict: float = 0.0,
) -> MemoryUnit:
    return MemoryUnit(
        key=key,
        semantic_similarity=similarity,
        observed_at=observed_at,
        historical_accuracy=accuracy,
        base_confidence=base,
        conflict_penalty=conflict,
    )


def _order(units: list[MemoryUnit], scenario: str, *, now: datetime = NOW) -> list[str]:
    return [item.key for item in rerank(units, weights=weights_for_scenario(scenario), now=now)]


def test_every_scenario_defines_weights_for_all_five_factors():
    assert set(DEFAULT_SCENARIO_WEIGHTS) == {
        SCENARIO_CUSTOMER_SERVICE,
        SCENARIO_PRODUCT_RECOMMENDATION,
        SCENARIO_RISK_ANALYSIS,
        SCENARIO_PROFILE_REVIEW,
    }
    for weights in DEFAULT_SCENARIO_WEIGHTS.values():
        assert set(weights) == {
            FACTOR_SEMANTIC_SIMILARITY,
            FACTOR_RECENCY,
            FACTOR_HISTORICAL_ACCURACY,
            FACTOR_BASE_CONFIDENCE,
            FACTOR_CONFLICT_PENALTY,
        }
        assert sum(weights.values()) == pytest.approx(1.0)


def test_product_recommendation_weights_similarity_highest_and_risk_weights_recency_highest():
    product = weights_for_scenario(SCENARIO_PRODUCT_RECOMMENDATION)
    risk = weights_for_scenario(SCENARIO_RISK_ANALYSIS)

    assert product[FACTOR_SEMANTIC_SIMILARITY] == max(product.values())
    assert risk[FACTOR_RECENCY] == max(risk.values())
    assert product[FACTOR_SEMANTIC_SIMILARITY] > risk[FACTOR_SEMANTIC_SIMILARITY]
    assert risk[FACTOR_RECENCY] > product[FACTOR_RECENCY]


def test_unknown_scenario_is_rejected_rather_than_silently_defaulted():
    with pytest.raises(ValueError, match=UNKNOWN_SCENARIO_MESSAGE):
        weights_for_scenario("不存在的场景")


def test_overrides_replace_a_scenarios_weights_without_touching_the_others():
    weights = weights_for_scenario(
        SCENARIO_PRODUCT_RECOMMENDATION,
        overrides={SCENARIO_PRODUCT_RECOMMENDATION: {FACTOR_SEMANTIC_SIMILARITY: 0.9}},
    )
    assert weights[FACTOR_SEMANTIC_SIMILARITY] == 0.9
    # 未覆盖的因子仍取缺省值，别的场景完全不受影响。
    assert weights[FACTOR_BASE_CONFIDENCE] == (
        DEFAULT_SCENARIO_WEIGHTS[SCENARIO_PRODUCT_RECOMMENDATION][FACTOR_BASE_CONFIDENCE]
    )
    assert weights_for_scenario(SCENARIO_RISK_ANALYSIS) == DEFAULT_SCENARIO_WEIGHTS[
        SCENARIO_RISK_ANALYSIS
    ]


def test_missing_factor_in_weights_is_rejected():
    with pytest.raises(ValueError):
        rerank([_unit("a")], weights={FACTOR_RECENCY: 1.0}, now=NOW)


def test_score_is_the_weighted_sum_of_the_five_factors():
    ranked = rerank(
        [_unit("a", similarity=1.0, accuracy=0.8, base=0.6, conflict=0.5)],
        weights=weights_for_scenario(SCENARIO_PRODUCT_RECOMMENDATION),
        now=NOW,
    )

    # 0.5*1.0 + 0.1*1.0(刚观测) + 0.1*0.8 + 0.2*0.6 - 0.1*0.5 = 0.75
    assert ranked[0].score == 0.75
    assert ranked[0].factors[FACTOR_CONFLICT_PENALTY] == -0.05


def test_the_same_units_rank_differently_under_two_scenarios():
    old = NOW - timedelta(days=800)
    units = [
        # 与查询高度相关，但很旧。
        _unit("relevant-old", similarity=1.0, observed_at=old, base=0.262),
        # 与查询不相关，但很新、基础分高。
        _unit("fresh-irrelevant", similarity=0.0, observed_at=NOW, base=0.9),
    ]

    assert _order(units, SCENARIO_PRODUCT_RECOMMENDATION) == ["relevant-old", "fresh-irrelevant"]
    assert _order(units, SCENARIO_RISK_ANALYSIS) == ["fresh-irrelevant", "relevant-old"]


def test_rerank_returns_every_unit_instead_of_filtering_low_scores():
    units = [
        _unit("high", similarity=1.0),
        _unit("mid", similarity=0.5),
        _unit("low", similarity=0.0, base=0.0, accuracy=0.0, conflict=1.0),
    ]

    ranked = rerank(units, weights=weights_for_scenario(SCENARIO_PROFILE_REVIEW), now=NOW)

    assert [item.key for item in ranked] == ["high", "mid", "low"]
    assert len(ranked) == len(units)


def test_conflict_penalty_pushes_two_otherwise_equal_units_apart():
    ranked = rerank(
        [_unit("clean"), _unit("conflicted", conflict=1.0)],
        weights=weights_for_scenario(SCENARIO_PROFILE_REVIEW),
        now=NOW,
    )

    assert [item.key for item in ranked] == ["clean", "conflicted"]


def test_recency_is_one_when_just_observed_and_zero_at_the_horizon():
    assert recency(NOW, NOW) == 1.0
    assert recency(NOW - timedelta(days=365), NOW) == 0.0
    # 观测时间晚于基准（时钟回拨）按「刚刚」处理，不产生大于 1 的时效性。
    assert recency(NOW + timedelta(days=10), NOW) == 1.0


def test_ranking_uses_the_passed_basis_not_the_wall_clock():
    units = [_unit("old", observed_at=datetime(2020, 1, 1, 12, 0, 0))]
    weights = weights_for_scenario(SCENARIO_RISK_ANALYSIS)

    fresh_basis = rerank(units, weights=weights, now=datetime(2020, 1, 2, 12, 0, 0))
    stale_basis = rerank(units, weights=weights, now=datetime(2026, 9, 17, 12, 0, 0))

    assert fresh_basis[0].factors[FACTOR_RECENCY] > 0
    assert stale_basis[0].factors[FACTOR_RECENCY] == 0.0


def test_ties_are_broken_by_key_so_the_order_never_drifts():
    ranked = rerank(
        [_unit("b"), _unit("a"), _unit("c")],
        weights=weights_for_scenario(SCENARIO_CUSTOMER_SERVICE),
        now=NOW,
    )

    assert [item.key for item in ranked] == ["a", "b", "c"]
