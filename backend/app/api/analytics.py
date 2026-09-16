from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.analytics.schemas import AnalyticsQueryRequest
from app.analytics.service import run_analytics_query
from app.auth.dependencies import current_employee
from app.db.models import Employee
from app.db.session import get_session
from app.http import ok
from app.settings import Settings, get_settings

router = APIRouter(prefix="/api/internal/analytics")


@router.post("/query")
def run_query(
    body: AnalyticsQueryRequest,
    employee: Employee = Depends(current_employee),
    db: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    # 任何内部员工都可提问；能查到哪些行由视图内建的行级权限决定，
    # 身份取自登录凭证（employee），不取自问题文本。
    answer = run_analytics_query(
        db, settings, employee=employee, question=body.question
    )
    return ok(answer.model_dump())
