"""推荐理由：引用客户画像的具体信息，而不是泛泛而谈。"""

from app.advisory.scoring import DIMENSION_RETURN, DIMENSION_TERM

_HIGH_SCORE = 0.66
_MID_SCORE = 0.33
_FULL_TERM_MATCH_SCORE = 0.99


def _score_of(candidate: dict, dimension: str) -> float:
    return next(item["score"] for item in candidate["score_breakdown"] if item["dimension"] == dimension)


def _risk_clause(candidate: dict, *, customer_risk_level: str) -> str:
    product_level = candidate["risk_level"]
    if product_level == customer_risk_level:
        return f"客户风险承受等级为 {customer_risk_level}，本产品风险等级 {product_level} 与其完全匹配"
    return f"客户风险承受等级为 {customer_risk_level}，本产品风险等级 {product_level} 更为稳健，在其承受范围之内"


def _return_clause(candidate: dict) -> str:
    score = _score_of(candidate, DIMENSION_RETURN)
    if score >= _HIGH_SCORE:
        level_desc = "处于候选池内较高水平"
    elif score >= _MID_SCORE:
        level_desc = "处于候选池内中等水平"
    else:
        level_desc = "处于候选池内较低水平"
    expected_return = format(candidate["expected_return"], "f")
    return f"预期年化收益 {expected_return}%，{level_desc}"


def _term_clause(candidate: dict, *, horizon_days: int) -> str:
    score = _score_of(candidate, DIMENSION_TERM)
    term_days = candidate["term_days"]
    if score >= _FULL_TERM_MATCH_SCORE:
        return f"期限 {term_days} 天，在其风险等级对应的 {horizon_days} 天配置周期以内，流动性无虞"
    return f"期限 {term_days} 天，超出其风险等级对应的 {horizon_days} 天配置周期，需权衡流动性"


def _preference_clause(candidate: dict, *, product_preference: dict) -> str | None:
    preferred_types = {item for values in product_preference.values() for item in values}
    if candidate["product_type"] in preferred_types:
        return f"产品类型「{candidate['product_type']}」符合画像记录的产品偏好"
    return None


def _experience_clause(*, investment_experience: str | None) -> str | None:
    if not investment_experience:
        return None
    return f"客户投资经验为「{investment_experience}」，与本产品的复杂度相称"


def build_reason(
    candidate: dict,
    *,
    customer_risk_level: str,
    product_preference: dict,
    horizon_days: int,
    investment_experience: str | None = None,
) -> str:
    # 风险等级与投资经验总是被引用；产品偏好只在命中时补充——这样理由不会
    # 因为没命中偏好标签就退化成只剩一条画像依据。
    clauses = [
        _risk_clause(candidate, customer_risk_level=customer_risk_level),
        _return_clause(candidate),
        _term_clause(candidate, horizon_days=horizon_days),
    ]
    experience_clause = _experience_clause(investment_experience=investment_experience)
    if experience_clause:
        clauses.append(experience_clause)
    preference_clause = _preference_clause(candidate, product_preference=product_preference)
    if preference_clause:
        clauses.append(preference_clause)
    return "；".join(clauses) + "。"
