"""图谱重建的编排：并发互斥、耗时统计、成败留痕。

Neo4j 那一侧的原子性（重建期间/失败时旧图谱仍可用）由单个写事务天然
保证，见 app.knowledge_graph.sync。这里只处理跨请求的并发互斥——两个
管理员同时点了手工触发，只有一个能真正跑——以及把每次重建的结果记进
MySQL，供 `GET /api/internal/graph/stats` 读。锁与留痕共用一张表，
不另开一把分布式锁：`lock_key` 进行中时固定取值，唯一约束保证同一时刻
只有一条记录能拿到它。
"""

import time
from datetime import datetime

from neo4j import Driver
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import GraphSyncRun
from app.exceptions import AppError
from app.knowledge_graph import sync

STATUS_RUNNING = "进行中"
STATUS_SUCCESS = "成功"
STATUS_FAILED = "失败"
_LOCK_VALUE = "running"
_FAILURE_REASON_MAX_LENGTH = 2000

ALREADY_RUNNING_MESSAGE = "图谱重建正在进行中，请稍后再试"


def _claim(db: Session, *, now: datetime) -> GraphSyncRun:
    run = GraphSyncRun(lock_key=_LOCK_VALUE, status=STATUS_RUNNING, started_at=now)
    db.add(run)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise AppError(409, ALREADY_RUNNING_MESSAGE) from None
    db.refresh(run)
    return run


def rebuild(db: Session, driver: Driver, *, namespace: str, now: datetime) -> dict:
    run = _claim(db, now=now)
    started = time.monotonic()
    try:
        stats = sync.rebuild_graph(db, driver, namespace=namespace)
    except Exception as exc:
        run.lock_key = None
        run.status = STATUS_FAILED
        run.duration_ms = int((time.monotonic() - started) * 1000)
        run.failure_reason = str(exc)[:_FAILURE_REASON_MAX_LENGTH]
        db.commit()
        raise

    run.lock_key = None
    run.status = STATUS_SUCCESS
    run.node_count = stats["node_count"]
    run.relationship_count = stats["relationship_count"]
    run.duration_ms = int((time.monotonic() - started) * 1000)
    db.commit()
    return get_status(db)


def get_status(db: Session) -> dict:
    latest = db.scalar(select(GraphSyncRun).order_by(GraphSyncRun.id.desc()).limit(1))
    latest_success = db.scalar(
        select(GraphSyncRun)
        .where(GraphSyncRun.status == STATUS_SUCCESS)
        .order_by(GraphSyncRun.id.desc())
        .limit(1)
    )
    return {
        "running": latest is not None and latest.lock_key is not None,
        "node_count": latest_success.node_count if latest_success else None,
        "relationship_count": latest_success.relationship_count if latest_success else None,
        "synced_at": latest_success.started_at if latest_success else None,
        "duration_ms": latest_success.duration_ms if latest_success else None,
        "last_attempt_status": latest.status if latest else None,
        "last_attempt_failure_reason": latest.failure_reason if latest else None,
    }
