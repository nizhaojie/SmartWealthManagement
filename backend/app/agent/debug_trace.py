"""调试级留痕：完整提示词、原始检索片段、数据查询的查询材料、token 与耗时明细。

审计级留痕是 `conversation_archive`（见 app.agent.archive），永久保存；这里是调试级，
保留期满后删除。两者分表存储，所以清理调试级在结构上就不可能碰到审计级。

清理接受一个**明确的**时间基准参数（ADR-0011），不在函数内部读系统时钟——否则
「保留期外的记录被删除、保留期内的不动」就只能靠等待真实时间流逝或改动系统时钟来
验证，实际上等于测不了。生产调用方（`POST /api/internal/traces/purge` 与将来的
周期任务）在最外层取一次当前时间传进来，一次批处理内所有记录用同一基准。
"""

from datetime import datetime, timedelta
from typing import cast

from sqlalchemy import delete, func, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from app.db.models import AgentDebugTrace
from app.tracing import get_trace_id


def record(
    db: Session,
    *,
    trace_id: str,
    agent_type: str,
    session_id: str | None = None,
    user_id: int | None = None,
    prompt: list | None = None,
    retrieval_snippets: list | None = None,
    data_query: dict | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    duration_ms: int | None = None,
) -> None:
    """记一条调试级留痕。什么时候由 `create_time` 的库默认值给出。"""
    db.add(
        AgentDebugTrace(
            trace_id=trace_id,
            session_id=session_id,
            user_id=user_id,
            agent_type=agent_type,
            prompt=prompt,
            retrieval_snippets=retrieval_snippets,
            data_query=data_query,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            duration_ms=duration_ms,
        )
    )
    db.commit()


def record_response_time(
    db: Session,
    *,
    agent_type: str,
    duration_ms: int,
    session_id: str | None = None,
    user_id: int | None = None,
) -> None:
    """只记耗时的一次留痕，供「各 Agent 的响应时间」统计使用。

    不借道 `record` 之外的表：`duration_ms` 本来就在这张表上，多开一张指标表会把
    「谁在什么时候答了一次、花了多久」拆成两处。提示词与检索片段留空——那不是
    这条记录要回答的问题。
    """
    record(
        db,
        trace_id=get_trace_id(),
        agent_type=agent_type,
        session_id=session_id,
        user_id=user_id,
        duration_ms=duration_ms,
    )


def response_time_summary(db: Session) -> list[dict]:
    """按 Agent 汇总响应时间：次数、平均、最快、最慢（毫秒）。

    只统计记了耗时的行；没有数据时返回空列表，而不是用 0 假装有一个数据点。
    """
    rows = db.execute(
        select(
            AgentDebugTrace.agent_type,
            func.count(AgentDebugTrace.id),
            func.avg(AgentDebugTrace.duration_ms),
            func.min(AgentDebugTrace.duration_ms),
            func.max(AgentDebugTrace.duration_ms),
        )
        .where(AgentDebugTrace.duration_ms.is_not(None))
        .group_by(AgentDebugTrace.agent_type)
        .order_by(AgentDebugTrace.agent_type)
    ).all()
    return [
        {
            "agent_type": agent_type,
            "count": int(count),
            "avg_duration_ms": round(float(avg), 1),
            "min_duration_ms": int(minimum),
            "max_duration_ms": int(maximum),
        }
        for agent_type, count, avg, minimum, maximum in rows
    ]


def purge(db: Session, *, now: datetime, retention_days: int) -> int:
    """删除 `create_time < now - retention_days` 的调试级留痕，返回删除条数。

    时间基准由参数传入（ADR-0011）。删除条数回给调用方，便于手工触发时确认
    「这一次到底清掉了多少」，而不是只能看日志。
    """
    cutoff = now - timedelta(days=retention_days)
    result = cast(
        CursorResult,
        db.execute(delete(AgentDebugTrace).where(AgentDebugTrace.create_time < cutoff)),
    )
    db.commit()
    return int(result.rowcount or 0)
