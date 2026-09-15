import json
from datetime import datetime
from decimal import Decimal
from typing import Any

import redis
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.customer_profile.confidence import (
    SOURCE_ADVISOR,
    SOURCE_INITIAL_CONFIDENCE,
    compute_confidence,
    source_rank,
)
from app.customer_profile.judgement import age_from_id_number, judge_profile
from app.db.models import (
    Customer,
    CustomerProfile,
    Holding,
    ProfileTag,
    ProfileTagConflict,
    RiskAssessment,
    Transaction,
)
from app.exceptions import AppError

CACHE_KEY_PREFIX = "customer_profile:"
CACHE_TTL_SECONDS = 300
PROFILE_MISSING_MESSAGE = "客户画像不存在"
CUSTOMER_MISSING_MESSAGE = "客户不存在"
UNKNOWN_TAG_MESSAGE = "未知的画像标签"
UNKNOWN_SOURCE_MESSAGE = "未知的标签来源"
REASON_REQUIRED_MESSAGE = "手工修正必须填写理由"

TAG_LABELS = {
    "risk_level": "风险承受等级",
    "investment_experience": "投资经验",
    "annual_income_range": "收入区间",
    "total_assets": "资产规模",
    "target_allocation": "目标配置",
    "product_preference": "产品偏好",
}

ALLOWED_TAG_KEYS = frozenset(TAG_LABELS)
ALLOWED_SOURCES = frozenset(SOURCE_INITIAL_CONFIDENCE)


def _cache_key(customer_id: int) -> str:
    return f"{CACHE_KEY_PREFIX}{customer_id}"


def _cache_get(cache: redis.Redis, customer_id: int) -> dict | None:
    try:
        raw = cache.get(_cache_key(customer_id))
    except redis.RedisError:
        return None
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _cache_set(cache: redis.Redis, customer_id: int, payload: dict) -> None:
    try:
        cache.set(
            _cache_key(customer_id),
            json.dumps(payload, ensure_ascii=False),
            ex=CACHE_TTL_SECONDS,
        )
    except redis.RedisError:
        return


def invalidate_profile_cache(cache: redis.Redis, customer_id: int) -> None:
    try:
        cache.delete(_cache_key(customer_id))
    except redis.RedisError:
        return


def _sync_profile_field(profile: CustomerProfile, tag_key: str, value: Any) -> None:
    if tag_key == "total_assets":
        profile.total_assets = Decimal(str(value))
        return
    if tag_key in {
        "risk_level",
        "investment_experience",
        "annual_income_range",
        "target_allocation",
        "product_preference",
    }:
        setattr(profile, tag_key, value)


def _require_profile(db: Session, customer_id: int) -> tuple[Customer, CustomerProfile]:
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise AppError(404, CUSTOMER_MISSING_MESSAGE)
    profile = db.scalar(select(CustomerProfile).where(CustomerProfile.customer_id == customer_id))
    if profile is None:
        raise AppError(404, PROFILE_MISSING_MESSAGE)
    return customer, profile


def _finish_write(db: Session, cache: redis.Redis, profile: CustomerProfile, customer_id: int, now: datetime) -> None:
    profile.computed_at = now
    db.commit()
    invalidate_profile_cache(cache, customer_id)


def write_tag(
    db: Session,
    cache: redis.Redis,
    *,
    customer_id: int,
    tag_key: str,
    value: Any,
    source: str,
    now: datetime,
    reason: str | None = None,
) -> None:
    if tag_key not in ALLOWED_TAG_KEYS:
        raise AppError(400, UNKNOWN_TAG_MESSAGE)
    if source not in ALLOWED_SOURCES:
        raise AppError(400, UNKNOWN_SOURCE_MESSAGE)
    if source == SOURCE_ADVISOR and not (reason and reason.strip()):
        raise AppError(400, REASON_REQUIRED_MESSAGE)

    _customer, profile = _require_profile(db, customer_id)
    existing = db.scalar(
        select(ProfileTag).where(
            ProfileTag.customer_id == customer_id,
            ProfileTag.tag_key == tag_key,
        )
    )
    if existing is None:
        db.add(
            ProfileTag(
                customer_id=customer_id,
                tag_key=tag_key,
                tag_value=value,
                source=source,
                evidence_count=0,
                observed_at=now,
                reason=reason.strip() if reason else None,
            )
        )
        _sync_profile_field(profile, tag_key, value)
        _finish_write(db, cache, profile, customer_id, now)
        return

    incoming_rank = source_rank(source)
    current_rank = source_rank(existing.source)
    if existing.tag_value == value:
        if incoming_rank < current_rank:
            return
        existing.evidence_count += 1
        if incoming_rank > current_rank:
            existing.source = source
            existing.observed_at = now
            existing.reason = reason.strip() if reason else existing.reason
        _finish_write(db, cache, profile, customer_id, now)
        return

    if incoming_rank < current_rank:
        return

    db.add(
        ProfileTagConflict(
            customer_id=customer_id,
            tag_key=tag_key,
            old_value=existing.tag_value,
            old_source=existing.source,
            new_value=value,
            new_source=source,
            changed_at=now,
            reason=reason.strip() if reason else None,
        )
    )
    existing.tag_value = value
    existing.source = source
    existing.evidence_count = 0
    existing.observed_at = now
    existing.reason = reason.strip() if reason else None
    _sync_profile_field(profile, tag_key, value)
    _finish_write(db, cache, profile, customer_id, now)


def _load_snapshot(db: Session, customer_id: int) -> dict:
    customer, profile = _require_profile(db, customer_id)
    tags = db.scalars(
        select(ProfileTag)
        .where(ProfileTag.customer_id == customer_id)
        .order_by(ProfileTag.id.asc())
    ).all()
    conflicts = db.scalars(
        select(ProfileTagConflict)
        .where(ProfileTagConflict.customer_id == customer_id)
        .order_by(ProfileTagConflict.id.asc())
    ).all()
    return {
        "customer_id": customer.id,
        "real_name": customer.real_name,
        "computed_at": profile.computed_at.isoformat(),
        "tags": [
            {
                "key": tag.tag_key,
                "value": tag.tag_value,
                "source": tag.source,
                "evidence_count": tag.evidence_count,
                "observed_at": tag.observed_at.isoformat(),
                "reason": tag.reason,
            }
            for tag in tags
        ],
        "conflict_records": [
            {
                "tag_key": row.tag_key,
                "old_value": row.old_value,
                "old_source": row.old_source,
                "new_value": row.new_value,
                "new_source": row.new_source,
                "changed_at": row.changed_at.isoformat(),
                "reason": row.reason,
            }
            for row in conflicts
        ],
    }


def _tag_lookup(tags: list[dict]) -> dict[str, Any]:
    return {item["key"]: item["value"] for item in tags}


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def _build_judgement(db: Session, customer_id: int, snapshot: dict, now: datetime) -> dict:
    customer, profile = _require_profile(db, customer_id)
    lookup = _tag_lookup(snapshot["tags"])
    income = lookup.get("annual_income_range", profile.annual_income_range)
    assets = _decimal_or_none(lookup.get("total_assets", profile.total_assets))
    experience = lookup.get("investment_experience", profile.investment_experience)
    assessment = db.scalar(
        select(RiskAssessment)
        .where(RiskAssessment.customer_id == customer_id)
        .order_by(RiskAssessment.id.desc())
    )
    holdings = db.scalars(select(Holding).where(Holding.customer_id == customer_id)).all()
    transaction_count = db.scalar(
        select(func.count()).select_from(Transaction).where(Transaction.customer_id == customer_id)
    )
    return judge_profile(
        age=age_from_id_number(customer.id_number, now.date()),
        annual_income_range=income,
        total_assets=assets,
        investment_experience=experience,
        risk_level=lookup.get("risk_level")
        or (assessment.risk_level if assessment else profile.risk_level),
        assessment_valid_until=assessment.valid_until if assessment else None,
        transaction_count=int(transaction_count or 0),
        holding_values=[row.current_value for row in holdings],
        now=now,
    )


def get_internal_profile(
    db: Session,
    cache: redis.Redis,
    *,
    customer_id: int,
    now: datetime,
) -> dict:
    snapshot = _cache_get(cache, customer_id)
    if snapshot is None:
        snapshot = _load_snapshot(db, customer_id)
        _cache_set(cache, customer_id, snapshot)

    conflict_counts: dict[str, int] = {}
    for record in snapshot["conflict_records"]:
        key = record["tag_key"]
        conflict_counts[key] = conflict_counts.get(key, 0) + 1

    tags = []
    for item in snapshot["tags"]:
        observed_at = datetime.fromisoformat(item["observed_at"])
        tags.append(
            {
                "key": item["key"],
                "label": TAG_LABELS[item["key"]],
                "value": item["value"],
                "source": item["source"],
                "confidence": compute_confidence(
                    source=item["source"],
                    evidence_count=item["evidence_count"],
                    conflict_count=conflict_counts.get(item["key"], 0),
                    observed_at=observed_at,
                    now=now,
                ),
                "observed_at": item["observed_at"],
            }
        )
    return {
        "customer_id": snapshot["customer_id"],
        "real_name": snapshot["real_name"],
        "computed_at": snapshot["computed_at"],
        "tags": tags,
        "conflict_records": snapshot["conflict_records"],
        "judgement": _build_judgement(db, customer_id, snapshot, now),
    }


def list_customers(db: Session) -> list[dict]:
    rows = db.scalars(select(Customer).order_by(Customer.id.asc())).all()
    profiles = {
        row.customer_id: row
        for row in db.scalars(select(CustomerProfile)).all()
    }
    return [
        {
            "id": customer.id,
            "username": customer.username,
            "real_name": customer.real_name,
            "customer_level": customer.customer_level,
            "risk_level": profiles[customer.id].risk_level if customer.id in profiles else None,
        }
        for customer in rows
    ]
