"""降级留痕：把「这一次走了降级路径」写成一行可统计的记录。

降级与错误是两回事。模型调用失败退回兜底回答、向量超时改用关键词检索、缓存不可用
直连数据库、图谱超时只用向量结果、事件总线不可用只记日志——这些情况下请求仍然是
成功的，使用者看到的是一个正常响应。正因为「使用者不会察觉」，它才需要留痕：spec
要求事后能回答「系统实际上有多少时间工作在降级状态下」，而日志文件答不了这个问题。

记录一次降级**不能反过来成为新的故障点**，因此有两条边界：

1. `record` 吞掉任何写入异常并记日志。降级是为了「服务继续」，如果为了留痕把请求
   弄挂，那就本末倒置了。
2. 写入走**自己的会话**（绑定同一个引擎），不共用调用方请求的事务。共用会让一次
   留痕顺带提交调用方尚未提交的写操作；这与事件订阅方另开会话是同一个理由
   （ADR-0013）。
"""

from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import DegradationTrace
from app.tracing import get_trace_id

logger = logging.getLogger("app.degradation")

# 被降级的外部依赖。取值是稳定标识，不是给人读的文案——统计按它分组。
DEPENDENCY_MODEL = "model"
DEPENDENCY_VECTOR = "vector_store"
DEPENDENCY_GRAPH = "graph"
DEPENDENCY_CACHE = "cache"
DEPENDENCY_EVENT_BUS = "event_bus"

# 降级原因。同一依赖可以有多种原因，统计按依赖分组、按原因下钻。
REASON_RETRY_EXHAUSTED = "retry_exhausted"
REASON_TIMEOUT = "timeout"
REASON_UNAVAILABLE = "unavailable"


def _sibling_session(source: Session) -> Session:
    """留痕自己的会话：绑定同一个引擎，但不共用调用方请求的事务。"""
    return Session(bind=source.get_bind())


def record(
    db: Session,
    *,
    dependency: str,
    reason: str,
    agent_type: str | None = None,
    trace_id: str | None = None,
    detail: str | None = None,
) -> None:
    """记一次降级。写入失败只记日志——留痕是增强，不该让请求跟着失败。"""
    try:
        with _sibling_session(db) as session:
            session.add(
                DegradationTrace(
                    dependency=dependency,
                    reason=reason,
                    agent_type=agent_type,
                    trace_id=trace_id or get_trace_id(),
                    detail=detail[:1000] if detail else None,
                )
            )
            session.commit()
    except Exception:  # noqa: BLE001 - 留痕边界：写不进去也不能影响这次请求
        logger.warning(
            "降级留痕写入失败 dependency=%s reason=%s", dependency, reason, exc_info=True
        )


def happened(db: Session, *, trace_id: str | None) -> bool:
    """这一次请求（按追踪标识）是否触发过降级。查询失败按「没有」处理。"""
    if not trace_id:
        return False
    try:
        count = db.scalar(
            select(func.count())
            .select_from(DegradationTrace)
            .where(DegradationTrace.trace_id == trace_id)
        )
    except Exception:  # noqa: BLE001 - 只读查询，失败不该影响这次响应
        logger.warning("降级留痕查询失败 trace_id=%s", trace_id, exc_info=True)
        return False
    return bool(count)


def summarize(db: Session) -> dict:
    """降级频次概览：总数 + 按依赖分组 + 按原因分组。

    两个分组维度回答的是不同的问题——按依赖看「哪个外部组件最不稳」，按原因看
    「是超时还是整个不可达」，从而决定该调超时阈值还是该修连接。
    """
    by_dependency = _count_by(db, DegradationTrace.dependency)
    by_reason = _count_by(db, DegradationTrace.reason)
    return {
        "total": sum(by_dependency.values()),
        "by_dependency": by_dependency,
        "by_reason": by_reason,
    }


def _count_by(db: Session, column) -> dict[str, int]:
    rows = db.execute(
        select(column, func.count(DegradationTrace.id)).group_by(column)
    ).all()
    return {str(value): int(count) for value, count in rows}
