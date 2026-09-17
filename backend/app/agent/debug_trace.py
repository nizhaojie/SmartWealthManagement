"""调试级留痕：完整提示词、原始检索片段、token 与耗时明细。

审计级留痕是 `conversation_archive`（见 app.agent.archive），永久保存；这里是调试级，
保留期满后删除。两者分表存储，所以清理调试级在结构上就不可能碰到审计级。

清理接受一个**明确的**时间基准参数（ADR-0011），不在函数内部读系统时钟——否则
「保留期外的记录被删除、保留期内的不动」就只能靠等待真实时间流逝或改动系统时钟来
验证，实际上等于测不了。生产调用方（`POST /api/internal/traces/purge` 与将来的
周期任务）在最外层取一次当前时间传进来，一次批处理内所有记录用同一基准。
"""

from datetime import datetime, timedelta
from typing import cast

from sqlalchemy import delete
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from app.db.models import AgentDebugTrace


def record(
    db: Session,
    *,
    trace_id: str,
    agent_type: str,
    session_id: str | None = None,
    user_id: int | None = None,
    prompt: list | None = None,
    retrieval_snippets: list | None = None,
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
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            duration_ms=duration_ms,
        )
    )
    db.commit()


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
