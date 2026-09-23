"""受限查询的编排：跑查询链路，留下永久记录，再返回或报错。

数据分析与风控监测两个 Agent 共用这一条链路（ADR-0007）：调用方传入自己的 Agent
配置与记忆命名空间，其余（生成、校验、执行、解读、留痕）完全一致。视图范围收在
Agent 配置里（``AgentConfig.view_names``），风控监测 Agent 因此只看得到预警统计
视图——「不新建一套查询链路」在代码上就是这一处复用。

多轮追问依赖短期记忆（与智能客服同一套 Redis 记忆，按员工 + 会话标识
命名空间隔离）：上一轮问题进入查询生成的上下文，「那上个季度呢」才能
被理解。只有成功作答的轮次进入记忆——答不上来的轮次不构成上下文。
"""

import time
from collections.abc import Collection

import redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent import debug_trace, memory
from app.agent.config import DATA_ANALYSIS_CONFIG, AgentConfig
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
from app.pagination import PageParams, count_matching, paginated_response
from app.settings import Settings

# 记忆命名空间：同一员工在数据分析与风控问答里的多轮上下文互不串味。
DEFAULT_MEMORY_NAMESPACE = "analytics"


def _memory_session(employee: Employee, session_id: str, namespace: str) -> str:
    # 与客服会话同库存储，按身份与用途命名空间隔离。
    return f"{namespace}:{employee.id}:{session_id}"


def run_query(
    db: Session,
    settings: Settings,
    *,
    employee: Employee,
    question: str,
    cache: redis.Redis | None = None,
    session_id: str | None = None,
    config: AgentConfig = DATA_ANALYSIS_CONFIG,
    memory_namespace: str = DEFAULT_MEMORY_NAMESPACE,
) -> AnalyticsQueryResponse:
    history: list[dict] = []
    if cache is not None and session_id:
        history = memory.get_history(
            cache, _memory_session(employee, session_id, memory_namespace)
        )

    graph = build_graph(db, settings, employee=employee, view_names=config.view_names)
    started = time.monotonic()
    final_state: AnalyticsState = graph.invoke(
        {"question": question, "history": history}
    )
    # 响应时间按 Agent 记一笔（数据分析与风控监测共用这条链路，agent_type 来自配置）。
    debug_trace.record_response_time(
        db,
        agent_type=config.name,
        duration_ms=int((time.monotonic() - started) * 1000),
        session_id=session_id,
        user_id=employee.id,
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
        memory_session = _memory_session(employee, session_id, memory_namespace)
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
        question, default=config.content_classification_default
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


def list_query_history(
    db: Session, *, employee: Employee, params: PageParams
) -> dict:
    """员工自己的历史查询一页：留痕表同时服务合规追溯与历史重用两个目的。

    `total` 是本人的留痕条数（`employee_id` 过滤之后），不是本页条数——历史是只增表，
    「一共问过多少次」不会随翻页变。排序键是留痕时间倒序 + 标识兜底（ADR-0024）：
    留痕时间是秒精度，同一秒提交的两次查询若不分先后，翻页时会在两页之间来回跳。
    """
    query = select(AnalyticsQueryAudit).where(
        AnalyticsQueryAudit.employee_id == employee.id
    )
    total = count_matching(db, query)
    rows = db.scalars(
        query.order_by(
            AnalyticsQueryAudit.create_time.desc(), AnalyticsQueryAudit.id.desc()
        )
        .offset(params.offset)
        .limit(params.page_size)
    ).all()
    # 条目形状仍由 `AnalyticsHistoryItem` 定义，只是落成 JSON 形态再交给分页响应：
    # `paginated_response` 拼的是可直接序列化的 dict，而 `create_time` 是 datetime。
    items = [
        AnalyticsHistoryItem(
            id=row.id,
            question=row.question,
            sql=row.generated_sql,
            status=row.status,
            row_count=row.row_count,
            truncated=row.truncated,
            error_code=row.error_code,
            create_time=row.create_time,
        ).model_dump(mode="json")
        for row in rows
    ]
    return paginated_response(items, total=total, params=params)


def list_example_questions(
    settings: Settings, *, view_names: Collection[str] | None = None
) -> list[AnalyticsExampleItem]:
    """示例问题：与注入提示词的「问题 → 查询」示例同源，改配置即改界面。

    ``view_names`` 把示例收窄到某个 Agent 的视图范围：风控监测界面不该提示
    员工去问持仓类问题。
    """
    examples = query_examples.load_examples(settings)
    if view_names is not None:
        examples = tuple(
            query_examples.examples_for_view_names(examples, view_names)
        )
    return [
        AnalyticsExampleItem(question=example.question) for example in examples
    ]
