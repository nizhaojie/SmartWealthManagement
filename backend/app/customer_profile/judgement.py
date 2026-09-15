from datetime import date, datetime
from decimal import Decimal

CODE_AGE_UNDER_18 = "AGE_UNDER_18"
CODE_AGE_OVER_80 = "AGE_OVER_80"
CODE_NO_INCOME_LOW_ASSETS = "NO_INCOME_LOW_ASSETS"
CODE_ASSESSMENT_EXPIRED = "ASSESSMENT_EXPIRED"

REASON_AGE_UNDER_18 = "年龄不足 18 岁，需人工审核"
REASON_AGE_OVER_80 = "年龄超过 80 岁，需人工审核"
REASON_NO_INCOME_LOW_ASSETS = "无收入且资产不足万元，仅允许购买 R1–R2 产品"
REASON_ASSESSMENT_EXPIRED = "风险评测已过期，画像权限已冻结，请重新评估"

NO_INCOME_VALUE = "无收入"
LOW_ASSET_THRESHOLD = Decimal("10000")

INCOME_SCORES = {
    "无收入": 0,
    "10万以下": 20,
    "10-30万": 40,
    "30-50万": 60,
    "50-100万": 80,
    "100万以上": 100,
}

EXPERIENCE_SCORES = {
    "无": 0,
    "0-1年": 20,
    "1-3年": 40,
    "3-5年": 60,
    "5-10年": 80,
    "10年以上": 100,
}

RISK_PREFERENCE_SCORES = {
    "C1": 20,
    "C2": 40,
    "C3": 60,
    "C4": 80,
    "C5": 100,
}

BASE_WEIGHT = 0.25
EXPERIENCE_WEIGHT = 0.25
PREFERENCE_WEIGHT = 0.30
BEHAVIOR_WEIGHT = 0.20


def age_from_id_number(id_number: str, today: date) -> int | None:
    if len(id_number) < 14:
        return None
    try:
        birth = date(int(id_number[6:10]), int(id_number[10:12]), int(id_number[12:14]))
    except ValueError:
        return None
    years = today.year - birth.year
    if (today.month, today.day) < (birth.month, birth.day):
        years -= 1
    return years


def _age_score(age: int) -> int:
    if age <= 25:
        return 50
    if age <= 40:
        return 80
    if age <= 55:
        return 70
    if age <= 70:
        return 50
    return 30


def _asset_score(amount: Decimal) -> int:
    if amount < Decimal("10000"):
        return 10
    if amount < Decimal("100000"):
        return 30
    if amount < Decimal("500000"):
        return 50
    if amount < Decimal("2000000"):
        return 70
    return 90


def _behavior_score(transaction_count: int, holding_values: list[Decimal]) -> int:
    if transaction_count == 0:
        score = 80
    elif transaction_count <= 5:
        score = 90
    elif transaction_count <= 20:
        score = 70
    else:
        score = 40
    total = sum(holding_values, Decimal("0"))
    if total > 0 and max(holding_values) / total >= Decimal("0.8"):
        score -= 20
    return max(0, score)


def _grade_weighted_score(score: float) -> str:
    if score < 20:
        return "C1"
    if score < 40:
        return "C2"
    if score < 60:
        return "C3"
    if score < 80:
        return "C4"
    return "C5"


def collect_circuit_breaks(
    *,
    age: int | None,
    annual_income_range: str | None,
    total_assets: Decimal | None,
    assessment_valid_until: date | None,
    today: date,
) -> list[dict[str, str]]:
    reasons: list[dict[str, str]] = []
    if age is not None and age < 18:
        reasons.append({"code": CODE_AGE_UNDER_18, "message": REASON_AGE_UNDER_18})
    if age is not None and age > 80:
        reasons.append({"code": CODE_AGE_OVER_80, "message": REASON_AGE_OVER_80})
    if (
        annual_income_range == NO_INCOME_VALUE
        and total_assets is not None
        and total_assets < LOW_ASSET_THRESHOLD
    ):
        reasons.append({"code": CODE_NO_INCOME_LOW_ASSETS, "message": REASON_NO_INCOME_LOW_ASSETS})
    if assessment_valid_until is not None and assessment_valid_until < today:
        reasons.append({"code": CODE_ASSESSMENT_EXPIRED, "message": REASON_ASSESSMENT_EXPIRED})
    return reasons


def judge_profile(
    *,
    age: int | None,
    annual_income_range: str | None,
    total_assets: Decimal | None,
    investment_experience: str | None,
    risk_level: str | None,
    assessment_valid_until: date | None,
    transaction_count: int,
    holding_values: list[Decimal],
    now: datetime,
) -> dict:
    reasons = collect_circuit_breaks(
        age=age,
        annual_income_range=annual_income_range,
        total_assets=total_assets,
        assessment_valid_until=assessment_valid_until,
        today=now.date(),
    )
    if reasons:
        return {
            "circuit_break": True,
            "reasons": reasons,
            "risk_level": None,
            "dimension_scores": None,
            "weighted_score": None,
        }

    age_points = _age_score(age) if age is not None else 0
    income_points = INCOME_SCORES.get(annual_income_range or "", 0)
    asset_points = _asset_score(total_assets) if total_assets is not None else 0
    base_score = round((age_points + income_points + asset_points) / 3, 2)
    experience_score = float(EXPERIENCE_SCORES.get(investment_experience or "", 0))
    preference_score = float(RISK_PREFERENCE_SCORES.get(risk_level or "", 0))
    behavior_score = float(_behavior_score(transaction_count, holding_values))
    weighted = round(
        base_score * BASE_WEIGHT
        + experience_score * EXPERIENCE_WEIGHT
        + preference_score * PREFERENCE_WEIGHT
        + behavior_score * BEHAVIOR_WEIGHT,
        2,
    )
    return {
        "circuit_break": False,
        "reasons": [],
        "risk_level": _grade_weighted_score(weighted),
        "dimension_scores": {
            "基础属性": base_score,
            "投资经验": experience_score,
            "风险偏好": preference_score,
            "行为异常": behavior_score,
        },
        "weighted_score": weighted,
    }
