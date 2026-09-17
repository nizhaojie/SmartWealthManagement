"""风控监测 Agent 的自然语言查询入口。

风控专员用日常语言提问（「今天有哪些高风险预警」），不必自己组合筛选条件。
落点在风控模块而不是数据分析模块：这里装配的是风控监测 Agent 的配置
（``app.agent.risk_query`` + ``RISK_MONITORING_CONFIG``），数据分析模块的回答
范围不受影响。

任何内部员工都可以提问；能查到哪些行由语义视图内建的行级权限决定——客户经理
只看得到名下客户的预警，身份取自登录凭证，不取自问题文本。
"""

import redis
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.agent.config import RISK_VIEW_NAMES
from app.agent.risk_query import run_risk_query
from app.analytics.schemas import AnalyticsQueryRequest
from app.analytics.service import list_example_questions
from app.auth.dependencies import current_employee
from app.db.models import Employee
from app.db.session import get_session
from app.http import ok
from app.redis_client import get_redis
from app.settings import Settings, get_settings

router = APIRouter(prefix="/api/internal/risk-monitoring")


@router.post("/query")
def run_query_endpoint(
    body: AnalyticsQueryRequest,
    employee: Employee = Depends(current_employee),
    db: Session = Depends(get_session),
    cache: redis.Redis = Depends(get_redis),
    settings: Settings = Depends(get_settings),
):
    answer = run_risk_query(
        db,
        settings,
        employee=employee,
        question=body.question,
        cache=cache,
        session_id=body.session_id,
    )
    return ok(answer.model_dump())


@router.get("/examples")
def get_examples(
    _employee: Employee = Depends(current_employee),
    settings: Settings = Depends(get_settings),
):
    items = list_example_questions(settings, view_names=RISK_VIEW_NAMES)
    return ok([item.model_dump() for item in items])
