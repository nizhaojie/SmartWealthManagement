"""数据分析查询的审计级留痕：每次查询留下永久记录。

提问人、问题、生成的查询、返回行数是合规要求的最低集；状态与业务
错误码让「谁试图越权取数」也可追溯——被拒绝的尝试同样留痕。
"""

from sqlalchemy.orm import Session

from app.analytics import errors
from app.db.models import AnalyticsQueryAudit, Employee

STATUS_SUCCESS = "成功"
STATUS_OUT_OF_SCOPE = "超出可查范围"
STATUS_GENERATION_FAILED = "生成失败"
STATUS_REJECTED = "校验拒绝"
STATUS_TIMEOUT = "查询超时"
STATUS_EXECUTION_FAILED = "执行失败"

STATUS_BY_ERROR_CODE = {
    errors.OUT_OF_SCOPE_CODE: STATUS_OUT_OF_SCOPE,
    errors.GENERATION_FAILED_CODE: STATUS_GENERATION_FAILED,
    errors.QUERY_REJECTED_CODE: STATUS_REJECTED,
    errors.QUERY_TIMEOUT_CODE: STATUS_TIMEOUT,
    errors.EXECUTION_FAILED_CODE: STATUS_EXECUTION_FAILED,
}


def record_query(
    db: Session,
    *,
    employee: Employee,
    question: str,
    generated_sql: str | None,
    status: str,
    row_count: int | None,
    truncated: bool,
    error_code: int | None,
) -> None:
    db.add(
        AnalyticsQueryAudit(
            employee_id=employee.id,
            question=question,
            generated_sql=generated_sql,
            status=status,
            row_count=row_count,
            truncated=truncated,
            error_code=error_code,
        )
    )
    db.commit()
