"""画像置信度的周期校准：重算全量置信度并标记过期标签。

标签的置信度是派生值，不单独落库（ADR-0012）；校准只做两件有持久效果的事：

1. 把时间衰减之后已经低于阈值的标签标记为**已过期**，于是画像面板能把「这条信息该重新
   确认了」与「这条信息是新鲜的」区分开；
2. 把每个画像的汇总置信度（``fin_customer_profile.confidence_score``）重算为标签置信度的
   均值——它是画像新鲜度的单一数字，供不看明细的读取方使用。

时间基准由参数显式传入，不在函数内部读时钟（ADR-0011）：否则「基准为某时刻时，恰好这
几条标签被标记过期」就只能靠等待真实时间流逝来验证，实际上等于测不了。生产调用方
（``POST /api/internal/profiles/calibrate`` 与将来的周期调度）在最外层取一次当前时间，
一次批处理内所有记录用同一基准。

``computed_at`` 不在这里改写：它记录的是画像**事实**的重算时间，校准只重算由事实派生的
置信度，改它会把「画像陈旧」的告警一并抹掉。
"""

from datetime import datetime
from decimal import Decimal

import redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.customer_profile.confidence import compute_confidence
from app.customer_profile.service import invalidate_profile_cache
from app.db.models import CustomerProfile, ProfileTag, ProfileTagConflict


def recalibrate(
    db: Session,
    *,
    now: datetime,
    expiry_threshold: float,
    cache: redis.Redis | None = None,
) -> dict:
    """重算所有画像标签的置信度，标记过期标签，返回本次校准的规模。

    阈值由调用方传入而不是写在函数里：它是可调的运营参数，也是测试断言「恰好这几条过期」
    的输入。``cache`` 为空时只改库不做缓存失效（纯计算场景）。
    """
    tags = list(db.scalars(select(ProfileTag).order_by(ProfileTag.id.asc())))
    conflict_counts = _conflict_counts(db)

    by_customer: dict[int, list[ProfileTag]] = {}
    for tag in tags:
        by_customer.setdefault(tag.customer_id, []).append(tag)

    expired_tags = 0
    for customer_id, customer_tags in by_customer.items():
        confidences = []
        for tag in customer_tags:
            confidence = compute_confidence(
                source=tag.source,
                evidence_count=tag.evidence_count,
                conflict_count=conflict_counts.get((customer_id, tag.tag_key), 0),
                observed_at=tag.observed_at,
                now=now,
            )
            confidences.append(confidence)
            tag.expired = confidence < expiry_threshold
            expired_tags += int(tag.expired)

        _update_profile_confidence(db, customer_id, confidences)
        if cache is not None:
            invalidate_profile_cache(cache, customer_id)

    db.commit()
    return {
        "customers": len(by_customer),
        "tags": len(tags),
        "expired_tags": expired_tags,
        "expiry_threshold": expiry_threshold,
        "basis": now.isoformat(),
    }


def _conflict_counts(db: Session) -> dict[tuple[int, str], int]:
    counts: dict[tuple[int, str], int] = {}
    for row in db.scalars(select(ProfileTagConflict)):
        key = (row.customer_id, row.tag_key)
        counts[key] = counts.get(key, 0) + 1
    return counts


def _update_profile_confidence(
    db: Session, customer_id: int, confidences: list[float]
) -> None:
    if not confidences:
        return
    profile = db.scalar(
        select(CustomerProfile).where(CustomerProfile.customer_id == customer_id)
    )
    if profile is None:
        return
    mean = sum(confidences) / len(confidences)
    profile.confidence_score = Decimal(str(round(mean, 2)))
