"""数据分析查询的编排：跑查询链路，留下永久记录，再返回或报错。

多轮追问依赖短期记忆（与智能客服同一套 Redis 记忆，按员工 + 会话标识
命名空间隔离）：上一轮问题进入查询生成的上下文，「那上个季度呢」才能
被理解。只有成功作答的轮次进入记忆——答不上来的轮次不构成上下文。
"""

import redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent import memory
from app.agent.config import DATA_ANALYSIS_CONFIG
from app.analytics import audit, classification
from app.analytics import examples as query_examples
from app.analytics.graph import AnalyticsState, build_graph
from app.analytics.schemas import (
    AnalyticsExampleItem,
    AnalyticsHistoryItem,
    AnalyticsQueryResponse,
)
from app.db.models import AnalyticsQueryAudit, Employee
from app.exceptions import AppError
from app.settings import Settings


def _memory_session(employee: Employee, session_id: str) -> str:
    # 与客服会话同库存储，按身份与用途命名空间隔离。
    return f"analytics:{employee.id}:{session_id}"


def run_analytics_query(
    db: Session,
    settings: Settings,
    *,
    employee: Employee,
    question: str,
    cache: redis.Redis | None = None,
    session_id: str | None = None,
) -> AnalyticsQueryResponse:
    history: list[dict] = []
    if cache is not None and session_id:
        history = memory.get_history(cache, _memory_session(employee, session_id))

    graph = build_graph(db, settings, employee=employee)
    final_state: AnalyticsState = graph.invoke(
        {"question": question, "history": history}
    )

    sql = final_state.get("sql")
    error_code = final_state.get("error_code")
    if error_code is not None:
        # 被拒绝 / 失败的尝试同样留痕：事后可追溯谁试图查了什么。
        audit.record_query(
            db,
            employee=employee,
            question=question,
            generated_sql=sql,
            status=audit.STATUS_BY_ERROR_CODE[error_code],
            row_count=None,
            truncated=False,
            error_code=error_code,
        )
        raise AppError(error_code, final_state["error_message"])

    result = final_state["result"]
    audit.record_query(
        db,
        employee=employee,
        question=question,
        generated_sql=sql,
        status=audit.STATUS_SUCCESS,
        row_count=len(result.rows),
        truncated=result.truncated,
        error_code=None,
    )
    if cache is not None and session_id:
        memory_session = _memory_session(employee, session_id)
        memory.append_turn(
            cache, memory_session, role="user", content=question, settings=settings
        )
        memory.append_turn(
            cache,
            memory_session,
            role="assistant",
            content=final_state["interpretation"],
            settings=settings,
        )

    # 内容分类默认值来自这份 Agent 配置（ADR-0007）；命中报告类问法时
    # 提升为投顾内容。
    content_classification = classification.classify_output(
        question, default=DATA_ANALYSIS_CONFIG.content_classification_default
    )
    return AnalyticsQueryResponse(
        question=question,
        sql=sql or "",
        columns=result.columns,
        rows=result.rows,
        row_count=len(result.rows),
        truncated=result.truncated,
        views=[view.name for view in final_state["views"]],
        interpretation=final_state["interpretation"],
        content_classification=content_classification,
        disclaimer=classification.disclaimer_for(content_classification),
    )


_HISTORY_LIMIT = 50


def list_query_history(
    db: Session, *, employee: Employee
) -> list[AnalyticsHistoryItem]:
    """员工自己的历史查询：留痕表同时服务合规追溯与历史重用两个目的。"""
    rows = db.scalars(
        select(AnalyticsQueryAudit)
        .where(AnalyticsQueryAudit.employee_id == employee.id)
        .order_by(AnalyticsQueryAudit.id.desc())
        .limit(_HISTORY_LIMIT)
    ).all()
    return [
        AnalyticsHistoryItem(
            id=row.id,
            question=row.question,
            sql=row.generated_sql,
            status=row.status,
            row_count=row.row_count,
            truncated=row.truncated,
            error_code=row.error_code,
            create_time=row.create_time,
        )
        for row in rows
    ]


def list_example_questions(settings: Settings) -> list[AnalyticsExampleItem]:
    """示例问题：与注入提示词的「问题 → 查询」示例同源，改配置即改界面。"""
    return [
        AnalyticsExampleItem(question=example.question)
        for example in query_examples.load_examples(settings)
    ]
