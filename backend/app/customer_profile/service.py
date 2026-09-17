import json
from datetime import datetime
from decimal import Decimal
from typing import Any

import redis
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import degradation
from app.customer_profile.confidence import (
    CONFLICT_PENALTY_STEP,
    SOURCE_ADVISOR,
    SOURCE_INITIAL_CONFIDENCE,
    compute_confidence,
    source_rank,
)
from app.customer_profile.judgement import age_from_id_number, judge_profile
from app.customer_profile.rerank import MemoryUnit, rerank, weights_for_scenario
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
from app.tracing import get_trace_id

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

# 综合重排的两项「原始信号」如何从标签自身的历史推出来：
# - 历史准确率：标签被后续独立证据确认的次数归一化，还没被确认过就是 0；
# - 冲突惩罚：被相反证据冲撞的次数归一化，和基础置信分里用的是同一个步长。
HISTORICAL_ACCURACY_PER_EVIDENCE = 0.25


def _cache_key(customer_id: int) -> str:
    return f"{CACHE_KEY_PREFIX}{customer_id}"


def _cache_get(cache: redis.Redis, customer_id: int) -> tuple[dict | None, bool]:
    """读缓存，返回 (快照, 是否降级)。缓存不可用时按未命中处理。"""
    try:
        raw = cache.get(_cache_key(customer_id))
    except redis.RedisError:
        return None, True
    if not raw:
        return None, False
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None, False
    return (payload if isinstance(payload, dict) else None), False


def _cache_set(cache: redis.Redis, customer_id: int, payload: dict) -> bool:
    """写缓存，返回是否成功。缓存是优化不是依赖，写不进去不影响这次读取。"""
    try:
        cache.set(
            _cache_key(customer_id),
            json.dumps(payload, ensure_ascii=False),
            ex=CACHE_TTL_SECONDS,
        )
    except redis.RedisError:
        return False
    return True


def invalidate_profile_cache(cache: redis.Redis, customer_id: int) -> bool:
    """失效画像缓存，返回是否成功。失败时缓存里可能留着旧快照（等 TTL 自然过期）。"""
    try:
        cache.delete(_cache_key(customer_id))
    except redis.RedisError:
        return False
    return True


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
    if not invalidate_profile_cache(cache, customer_id):
        # 失效失败意味着读方可能继续拿到旧快照，属于缓存降级；留痕以便统计。
        degradation.record(
            db,
            dependency=degradation.DEPENDENCY_CACHE,
            reason=degradation.REASON_UNAVAILABLE,
            trace_id=get_trace_id(),
        )


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
        # 又确认了一次，这条标签不再是「该重新确认的旧信息」。
        existing.expired = False
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
    # 改写后的值是新写入的，过期标记随之复位。
    existing.expired = False
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
                "expired": bool(tag.expired),
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
    scenario: str | None = None,
    query: str | None = None,
    weights_overrides: dict[str, dict[str, float]] | None = None,
) -> dict:
    """读取客户画像。

    不传 ``scenario`` 时保持标签的写入顺序（既有行为）；传了则按该场景的五因子权重
    重排——同一批标签在「产品推荐」与「风险研判」下先后不同。重排只改变顺序，不删标签：
    低分的排在后面，取舍由调用方决定（见 `rerank.rerank`）。
    """
    snapshot, cache_degraded = _cache_get(cache, customer_id)
    if snapshot is None:
        # 缓存不可用（或未命中）都直连数据库；读到之后尝试回填，缓存恢复后下一次
        # 命中即可——Cache-Aside 的「恢复后自动回填」不需要额外的补偿任务。
        snapshot = _load_snapshot(db, customer_id)
        if not _cache_set(cache, customer_id, snapshot):
            cache_degraded = True
    if cache_degraded:
        degradation.record(
            db,
            dependency=degradation.DEPENDENCY_CACHE,
            reason=degradation.REASON_UNAVAILABLE,
            trace_id=get_trace_id(),
        )

    conflict_counts: dict[str, int] = {}
    for record in snapshot["conflict_records"]:
        key = record["tag_key"]
        conflict_counts[key] = conflict_counts.get(key, 0) + 1
    evidence_counts = {item["key"]: item["evidence_count"] for item in snapshot["tags"]}

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
                "expired": item.get("expired", False),
            }
        )

    if scenario is not None:
        tags = _rank_tags(
            tags,
            evidence_counts=evidence_counts,
            conflict_counts=conflict_counts,
            scenario=scenario,
            query=query,
            now=now,
            weights_overrides=weights_overrides,
        )

    return {
        "customer_id": snapshot["customer_id"],
        "real_name": snapshot["real_name"],
        "computed_at": snapshot["computed_at"],
        "tags": tags,
        "conflict_records": snapshot["conflict_records"],
        "judgement": _build_judgement(db, customer_id, snapshot, now),
    }


def _rank_tags(
    tags: list[dict],
    *,
    evidence_counts: dict[str, int],
    conflict_counts: dict[str, int],
    scenario: str,
    query: str | None,
    now: datetime,
    weights_overrides: dict[str, dict[str, float]] | None,
) -> list[dict]:
    """把标签适配成记忆单元交给重排纯函数，再把得分挂回标签回复。"""
    units = [
        MemoryUnit(
            key=tag["key"],
            semantic_similarity=_similarity_to_query(tag, query),
            observed_at=datetime.fromisoformat(tag["observed_at"]),
            historical_accuracy=_historical_accuracy(evidence_counts.get(tag["key"], 0)),
            base_confidence=tag["confidence"],
            conflict_penalty=_conflict_penalty(conflict_counts.get(tag["key"], 0)),
        )
        for tag in tags
    ]
    ranked = rerank(
        units,
        weights=weights_for_scenario(scenario, overrides=weights_overrides),
        now=now,
    )
    by_key = {tag["key"]: tag for tag in tags}
    return [
        {**by_key[unit.key], "rerank_score": unit.score, "rerank_factors": unit.factors}
        for unit in ranked
    ]


def _historical_accuracy(evidence_count: int) -> float:
    return min(1.0, max(evidence_count, 0) * HISTORICAL_ACCURACY_PER_EVIDENCE)


def _conflict_penalty(conflict_count: int) -> float:
    return min(1.0, max(conflict_count, 0) * CONFLICT_PENALTY_STEP)


def _similarity_to_query(tag: dict, query: str | None) -> float:
    """标签与当前查询的相关度。

    没有查询时所有标签同等相关（取 1.0），重排的顺序差异只来自其余四个因子；
    有查询时用关键词重合度近似语义相似度——不额外调模型，与检索链路「向量超时降级为
    关键词检索」同一思路，也是能让同一批标签在不同查询下先后翻转的那一项。
    """
    if not query or not query.strip():
        return 1.0
    return _keyword_similarity(f"{tag['label']} {_stringify(tag['value'])}", query)


def _stringify(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _keyword_similarity(text: str, query: str) -> float:
    text_grams = _bigrams(text)
    query_grams = _bigrams(query)
    if not text_grams or not query_grams:
        return 0.0
    return round(len(text_grams & query_grams) / len(text_grams | query_grams), 4)


def _bigrams(text: str) -> set[str]:
    # 中文没有空格分词，按相邻两字切；英文与数字先转成小写，标点不参与。
    chars = [char.lower() for char in text if char.isalnum()]
    return {f"{chars[index]}{chars[index + 1]}" for index in range(len(chars) - 1)}


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
