"""推荐理由：引用客户画像的具体信息（issue 01）。"""

from decimal import Decimal

from app.advisory.reasons import build_reason
from app.advisory.scoring import TILT_BALANCED, rank_candidates

PRODUCT = {
    "product_code": "F000003",
    "product_name": "天璇混合基金",
    "product_type": "混合基金",
    "risk_level": "R3",
    "expected_return": Decimal("8.0000"),
    "term_days": 0,
}


def _ranked(product: dict, *, customer_risk_level: str) -> dict:
    return rank_candidates([product], customer_risk_level=customer_risk_level, tilt=TILT_BALANCED)[0]


def test_reason_cites_the_customers_own_risk_level():
    candidate = _ranked(PRODUCT, customer_risk_level="C3")
    reason = build_reason(
        candidate,
        customer_risk_level="C3",
        product_preference={"基金": ["混合基金"]},
        horizon_days=270,
    )
    assert "C3" in reason
    assert candidate["risk_level"] in reason


def test_reason_mentions_product_preference_only_when_it_matches():
    candidate = _ranked(PRODUCT, customer_risk_level="C3")

    matching = build_reason(
        candidate,
        customer_risk_level="C3",
        product_preference={"基金": ["混合基金"]},
        horizon_days=270,
    )
    assert "产品偏好" in matching

    not_matching = build_reason(
        candidate,
        customer_risk_level="C3",
        product_preference={"基金": ["债券基金"]},
        horizon_days=270,
    )
    assert "产品偏好" not in not_matching


def test_reason_cites_the_expected_return_figure():
    candidate = _ranked(PRODUCT, customer_risk_level="C3")
    reason = build_reason(
        candidate, customer_risk_level="C3", product_preference={}, horizon_days=270
    )
    assert "8.0000%" in reason


def test_reason_cites_investment_experience_even_without_a_preference_match():
    # 产品偏好不命中时，理由不应退化成只剩风险等级一条画像依据。
    candidate = _ranked(PRODUCT, customer_risk_level="C3")
    reason = build_reason(
        candidate,
        customer_risk_level="C3",
        product_preference={"基金": ["债券基金"]},
        horizon_days=270,
        investment_experience="3-5年",
    )
    assert "3-5年" in reason
    assert "产品偏好" not in reason
