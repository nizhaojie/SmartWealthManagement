import redis
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.agent.config import DATA_ANALYSIS_CONFIG
from app.analytics.schemas import AnalyticsQueryRequest
from app.analytics.service import (
    list_example_questions,
    list_query_history,
    run_query,
)
from app.auth.dependencies import AuthContext, current_employee, require_internal
from app.db.models import Employee
from app.db.session import get_session
from app.http import ok
from app.pagination import PageParams, page_params
from app.redis_client import get_redis
from app.settings import Settings, get_settings

router = APIRouter(prefix="/api/internal/analytics")


@router.post("/query")
def run_analytics_query(
    body: AnalyticsQueryRequest,
    auth: AuthContext = Depends(require_internal),
    employee: Employee = Depends(current_employee),
    db: Session = Depends(get_session),
    cache: redis.Redis = Depends(get_redis),
    settings: Settings = Depends(get_settings),
):
    # 任何内部员工都可提问；能查到哪些行由视图内建的行级权限决定，
    # 身份取自登录凭证（employee），不取自问题文本。
    # 会话标识同理：缺省时取凭证里的 sid，于是同一场登录里的追问共用一个上下文，
    # 刷新与切模块都不打断；显式带值时以请求体为准——界面「清空对话」靠它换话题。
    answer = run_query(
        db,
        settings,
        employee=employee,
        question=body.question,
        cache=cache,
        session_id=body.session_id or auth.session_id,
    )
    return ok(answer.model_dump())


@router.get("/history")
def get_history(
    employee: Employee = Depends(current_employee),
    db: Session = Depends(get_session),
    page: PageParams = Depends(page_params),
):
    """本员工的历史查询，分页返回（ADR-0024）。"""
    return ok(list_query_history(db, employee=employee, params=page))


@router.get("/examples")
def get_examples(
    _employee: Employee = Depends(current_employee),
    settings: Settings = Depends(get_settings),
):
    # 收窄到数据分析 Agent 自己的视图范围：示例与视图一样分域，员工侧不提示
    # 客户问自己账目的那些问法（ADR-0025）。
    items = list_example_questions(settings, view_names=DATA_ANALYSIS_CONFIG.view_names)
    return ok([item.model_dump() for item in items])
