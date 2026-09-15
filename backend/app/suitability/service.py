from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.customer_profile.judgement import (
    CODE_ASSESSMENT_EXPIRED,
    CODE_NO_INCOME_LOW_ASSETS,
    REASON_ASSESSMENT_EXPIRED,
    age_from_id_number,
    collect_circuit_breaks,
)
from app.db.models import Customer, CustomerProfile, Product, RiskAssessment, SuitabilityDecision
from app.exceptions import AppError
from app.suitability.rules import (
    NO_INCOME_LOW_ASSETS_MAX_LEVEL,
    allowed_product_risk_levels,
    cap_product_risk_levels,
)

ASSESSMENT_MISSING_MESSAGE = "暂无风险测评记录"
PROFILE_MISSING_MESSAGE = "客户画像不存在"
CUSTOMER_MISSING_MESSAGE = "客户不存在"


def _latest_assessment(db: Session, customer_id: int) -> RiskAssessment:
    assessment = db.scalar(
        select(RiskAssessment)
        .where(RiskAssessment.customer_id == customer_id)
        .order_by(RiskAssessment.id.desc())
    )
    if assessment is None:
        raise AppError(404, ASSESSMENT_MISSING_MESSAGE)
    return assessment


def _require_customer_profile(db: Session, customer_id: int) -> tuple[Customer, CustomerProfile]:
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise AppError(404, CUSTOMER_MISSING_MESSAGE)
    profile = db.scalar(select(CustomerProfile).where(CustomerProfile.customer_id == customer_id))
    if profile is None:
        raise AppError(404, PROFILE_MISSING_MESSAGE)
    return customer, profile


def _record_decision(
    db: Session,
    *,
    customer_id: int,
    assessment: RiskAssessment,
    allowed: tuple[str, ...],
    now: datetime,
) -> None:
    db.add(
        SuitabilityDecision(
            customer_id=customer_id,
            assessment_id=assessment.id,
            customer_risk_level=assessment.risk_level,
            allowed_product_risk_levels=list(allowed),
            decided_at=now,
        )
    )
    db.commit()


def _allowed_for_customer(
    db: Session, *, customer_id: int, assessment: RiskAssessment, now: datetime
) -> tuple[str, ...]:
    customer, profile = _require_customer_profile(db, customer_id)
    reasons = collect_circuit_breaks(
        age=age_from_id_number(customer.id_number, now.date()),
        annual_income_range=profile.annual_income_range,
        total_assets=profile.total_assets,
        assessment_valid_until=assessment.valid_until,
        today=now.date(),
    )
    codes = {item["code"] for item in reasons}
    if CODE_ASSESSMENT_EXPIRED in codes:
        _record_decision(db, customer_id=customer_id, assessment=assessment, allowed=(), now=now)
        raise AppError(403, REASON_ASSESSMENT_EXPIRED)
    allowed = allowed_product_risk_levels(assessment.risk_level)
    if CODE_NO_INCOME_LOW_ASSETS in codes:
        allowed = cap_product_risk_levels(allowed, NO_INCOME_LOW_ASSETS_MAX_LEVEL)
    return allowed


def _serialize_product(product: Product) -> dict:
    return {
        "product_code": product.product_code,
        "product_name": product.product_name,
        "product_type": product.product_type,
        "risk_level": product.risk_level,
    }


def get_candidate_pool(
    db: Session,
    *,
    customer_id: int,
    now: datetime,
) -> dict:
    assessment = _latest_assessment(db, customer_id)
    allowed = _allowed_for_customer(db, customer_id=customer_id, assessment=assessment, now=now)
    products: list[Product] = []
    if allowed:
        products = list(
            db.scalars(
                select(Product)
                .where(Product.risk_level.in_(allowed), Product.status == "在售")
                .order_by(Product.product_code.asc())
            ).all()
        )
    _record_decision(
        db,
        customer_id=customer_id,
        assessment=assessment,
        allowed=allowed,
        now=now,
    )
    return {
        "assessment_id": assessment.id,
        "customer_risk_level": assessment.risk_level,
        "allowed_product_risk_levels": list(allowed),
        "products": [_serialize_product(row) for row in products],
    }


def list_suitability_decisions(db: Session, *, customer_id: int) -> list[dict]:
    _require_customer_profile(db, customer_id)
    rows = db.scalars(
        select(SuitabilityDecision)
        .where(SuitabilityDecision.customer_id == customer_id)
        .order_by(SuitabilityDecision.id.asc())
    ).all()
    return [
        {
            "id": row.id,
            "assessment_id": row.assessment_id,
            "customer_risk_level": row.customer_risk_level,
            "allowed_product_risk_levels": row.allowed_product_risk_levels,
            "decided_at": row.decided_at.isoformat(),
        }
        for row in rows
    ]
