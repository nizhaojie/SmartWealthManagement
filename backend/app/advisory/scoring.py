"""候选池内排序：按收益、风险、期限匹配度加权打分。

候选池已由适当性硬过滤保证合规（见 app.suitability），这里只做排序与
阐述，不重新判断一款产品是否允许被推荐给这位客户——那件事已经由结构
保证，不需要也不应该再交给这里的算法或未来接入的模型去裁量。

每项维度的得分与贡献都单独保留在 score_breakdown 里，而不是只算出一个
总分——顾问要能看出排序是不是合理，一个不可拆解的总分做不到这一点。
"""

from decimal import Decimal
from typing import TypedDict

DIMENSION_RETURN = "收益"
DIMENSION_RISK = "风险"
DIMENSION_TERM = "期限匹配度"
DIMENSIONS = (DIMENSION_RETURN, DIMENSION_RISK, DIMENSION_TERM)

TILT_BALANCED = "均衡"
TILT_RETURN = "收益优先"
TILT_LIQUIDITY = "流动性优先"
ALLOWED_TILTS = (TILT_BALANCED, TILT_RETURN, TILT_LIQUIDITY)

TILT_WEIGHTS: dict[str, dict[str, float]] = {
    TILT_BALANCED: {DIMENSION_RETURN: 1 / 3, DIMENSION_RISK: 1 / 3, DIMENSION_TERM: 1 / 3},
    TILT_RETURN: {DIMENSION_RETURN: 0.6, DIMENSION_RISK: 0.2, DIMENSION_TERM: 0.2},
    TILT_LIQUIDITY: {DIMENSION_RETURN: 0.2, DIMENSION_RISK: 0.2, DIMENSION_TERM: 0.6},
}

# 客户风险承受等级对应的可接受持有周期（天）：等级越高，愿意接受的锁定期越长。
# 产品期限在这个周期以内视为完全匹配，超出后按超出比例扣分。
TERM_HORIZON_DAYS = {"C1": 90, "C2": 180, "C3": 270, "C4": 365, "C5": 540}

_MAX_LEVEL_GAP = 4  # R1..R5 / C1..C5 共 5 级，最大级差为 4


class CandidateInput(TypedDict):
    product_code: str
    product_name: str
    product_type: str
    risk_level: str
    expected_return: Decimal
    term_days: int


def weights_for_tilt(tilt: str) -> dict[str, float]:
    return TILT_WEIGHTS[tilt]


def _level_rank(level: str) -> int:
    return int(level[1:])


def _return_scores(products: list[CandidateInput]) -> dict[str, float]:
    values = {p["product_code"]: p["expected_return"] for p in products}
    low, high = min(values.values()), max(values.values())
    if high == low:
        return {code: 1.0 for code in values}
    spread = high - low
    return {code: float((value - low) / spread) for code, value in values.items()}


def _risk_score(product_risk_level: str, customer_risk_level: str) -> float:
    gap = abs(_level_rank(customer_risk_level) - _level_rank(product_risk_level))
    return max(0.0, 1 - gap / _MAX_LEVEL_GAP)


def _term_score(term_days: int, horizon_days: int) -> float:
    if term_days <= horizon_days:
        return 1.0
    overrun = term_days - horizon_days
    return max(0.0, 1 - overrun / horizon_days)


def rank_candidates(
    products: list[CandidateInput],
    *,
    customer_risk_level: str,
    tilt: str,
) -> list[dict]:
    """在候选池内排序，产出每款产品可拆解的维度得分与加权总分。"""
    if not products:
        return []

    weights = weights_for_tilt(tilt)
    horizon_days = TERM_HORIZON_DAYS[customer_risk_level]
    return_scores = _return_scores(products)

    ranked: list[dict] = []
    for product in products:
        scores = {
            DIMENSION_RETURN: return_scores[product["product_code"]],
            DIMENSION_RISK: _risk_score(product["risk_level"], customer_risk_level),
            DIMENSION_TERM: _term_score(product["term_days"], horizon_days),
        }
        raw_values = {
            DIMENSION_RETURN: f"{format(product['expected_return'], 'f')}%",
            DIMENSION_RISK: product["risk_level"],
            DIMENSION_TERM: f"{product['term_days']}天",
        }
        contributions = {
            dimension: round(weights[dimension] * scores[dimension], 4) for dimension in DIMENSIONS
        }
        breakdown = [
            {
                "dimension": dimension,
                "raw_value": raw_values[dimension],
                "score": round(scores[dimension], 4),
                "weight": round(weights[dimension], 4),
                "contribution": contributions[dimension],
            }
            for dimension in DIMENSIONS
        ]
        composite_score = round(sum(contributions.values()), 4)
        ranked.append(
            {
                **product,
                "composite_score": composite_score,
                "score_breakdown": breakdown,
            }
        )

    ranked.sort(key=lambda item: (-item["composite_score"], item["product_code"]))
    return ranked
