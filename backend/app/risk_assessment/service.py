import json
from datetime import date, datetime

import redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.customer_profile.confidence import SOURCE_QUESTIONNAIRE
from app.customer_profile.service import write_tag
from app.db.models import CustomerProfile, RiskAssessment
from app.exceptions import AppError
from app.risk_assessment.grading import grade_total_score, valid_until_from
from app.risk_assessment.questionnaire import OPTION_SCORE, QUESTION_BY_ID, public_questions

DRAFT_KEY_PREFIX = "risk_assessment:draft:"
INVALID_ANSWER_MESSAGE = "答题内容无效"
INCOMPLETE_ANSWER_MESSAGE = "请完成全部题目后再提交"
PROFILE_MISSING_MESSAGE = "客户画像不存在"
ASSESSMENT_MISSING_MESSAGE = "暂无风险测评记录"
ASSESSOR_TYPE = "客户自测"


def _draft_key(customer_id: int) -> str:
    return f"{DRAFT_KEY_PREFIX}{customer_id}"


def _validate_answers(answers: dict[str, str], *, require_complete: bool = False) -> dict[str, str]:
    if require_complete and set(answers) != set(QUESTION_BY_ID):
        raise AppError(400, INCOMPLETE_ANSWER_MESSAGE)
    normalized: dict[str, str] = {}
    for question_id, option_id in answers.items():
        question = QUESTION_BY_ID.get(question_id)
        if question is None:
            raise AppError(400, INVALID_ANSWER_MESSAGE)
        if option_id not in {option.id for option in question.options}:
            raise AppError(400, INVALID_ANSWER_MESSAGE)
        normalized[question_id] = option_id
    return normalized


def save_draft(cache: redis.Redis, *, customer_id: int, answers: dict[str, str]) -> dict[str, str]:
    normalized = _validate_answers(answers)
    cache.set(_draft_key(customer_id), json.dumps(normalized, ensure_ascii=False))
    return normalized


def load_draft(cache: redis.Redis, *, customer_id: int) -> dict[str, str]:
    raw = cache.get(_draft_key(customer_id))
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}
    return {str(key): str(value) for key, value in payload.items()}


def clear_draft(cache: redis.Redis, *, customer_id: int) -> None:
    cache.delete(_draft_key(customer_id))


def get_questionnaire(cache: redis.Redis, *, customer_id: int) -> dict:
    return {"questions": public_questions(), "answers": load_draft(cache, customer_id=customer_id)}


def customer_visible_result(*, risk_level: str, valid_until: date) -> dict:
    return {"risk_level": risk_level, "valid_until": valid_until.isoformat()}


def submit_assessment(
    db: Session,
    cache: redis.Redis,
    *,
    customer_id: int,
    answers: dict[str, str],
    now: datetime,
) -> dict:
    normalized = _validate_answers(answers, require_complete=True)
    scored: list[dict[str, str | int]] = []
    total = 0
    for question_id, option_id in normalized.items():
        score = OPTION_SCORE[(question_id, option_id)]
        scored.append(
            {
                "question_id": question_id,
                "option_id": option_id,
                "score": score,
            }
        )
        total += score
    risk_level = grade_total_score(total)
    assessment_date = now.date()
    valid_until = valid_until_from(assessment_date)

    db.add(
        RiskAssessment(
            customer_id=customer_id,
            assessment_date=assessment_date,
            total_score=total,
            risk_level=risk_level,
            answers=scored,
            assessor_type=ASSESSOR_TYPE,
            valid_until=valid_until,
        )
    )

    profile = db.scalar(select(CustomerProfile).where(CustomerProfile.customer_id == customer_id))
    if profile is None:
        raise AppError(404, PROFILE_MISSING_MESSAGE)
    profile.risk_score = total
    write_tag(
        db,
        cache,
        customer_id=customer_id,
        tag_key="risk_level",
        value=risk_level,
        source=SOURCE_QUESTIONNAIRE,
        now=now,
    )
    clear_draft(cache, customer_id=customer_id)
    return customer_visible_result(risk_level=risk_level, valid_until=valid_until)


def get_current_result(db: Session, *, customer_id: int) -> dict:
    assessment = db.scalar(
        select(RiskAssessment)
        .where(RiskAssessment.customer_id == customer_id)
        .order_by(RiskAssessment.id.desc())
    )
    if assessment is None:
        raise AppError(404, ASSESSMENT_MISSING_MESSAGE)
    return customer_visible_result(risk_level=assessment.risk_level, valid_until=assessment.valid_until)


def list_assessments(db: Session, *, customer_id: int) -> list[dict]:
    rows = db.scalars(
        select(RiskAssessment)
        .where(RiskAssessment.customer_id == customer_id)
        .order_by(RiskAssessment.id.asc())
    ).all()
    return [
        {
            "id": row.id,
            "assessment_date": row.assessment_date.isoformat(),
            "risk_level": row.risk_level,
            "total_score": row.total_score,
            "valid_until": row.valid_until.isoformat(),
        }
        for row in rows
    ]
