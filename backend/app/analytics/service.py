"""数据分析查询的编排：跑查询链路，留下永久记录，再返回或报错。"""

from sqlalchemy.orm import Session

from app.analytics import audit
from app.analytics.graph import AnalyticsState, build_graph
from app.analytics.schemas import AnalyticsQueryResponse
from app.db.models import Employee
from app.exceptions import AppError
from app.settings import Settings


def run_analytics_query(
    db: Session,
    settings: Settings,
    *,
    employee: Employee,
    question: str,
) -> AnalyticsQueryResponse:
    graph = build_graph(db, settings, employee=employee)
    final_state: AnalyticsState = graph.invoke({"question": question})

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
    return AnalyticsQueryResponse(
        question=question,
        sql=sql or "",
        columns=result.columns,
        rows=result.rows,
        row_count=len(result.rows),
        truncated=result.truncated,
        views=[view.name for view in final_state["views"]],
    )
