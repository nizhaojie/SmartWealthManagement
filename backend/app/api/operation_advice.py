"""操作建议的两个内部入口：客户经理发起原稿，理财顾问放行或驳回。

`CONTEXT.md`「客户经理」：可以为名下客户发起操作建议——它只发起，放行是理财顾问的
事。因此发起路由只对客户经理开放（归属校验在 `app.operation_advice.service`），
放行与驳回只对理财顾问开放。生成本身在业务操作 Agent 里、审核在审核流水线上，
这里只做参数拼装。
"""

from datetime import datetime, timezone

import redis
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.dependencies import require_employee_role
from app.auth.roles import ACCOUNT_MANAGER, ADVISOR
from app.db.models import Employee
from app.db.session import get_session
from app.http import ok
from app.operation_advice.review import reject_advice, release_advice
from app.operation_advice.schemas import (
    OperationAdviceRejectRequest,
    OperationAdviceRequest,
)
from app.operation_advice.service import generate_operation_advice
from app.redis_client import get_redis

router = APIRouter(prefix="/api/internal/customers")
review_router = APIRouter(prefix="/api/internal/operation-advice")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@router.post("/{customer_id}/operation-advice")
def create_operation_advice(
    customer_id: int,
    body: OperationAdviceRequest,
    employee: Employee = Depends(require_employee_role(ACCOUNT_MANAGER)),
    db: Session = Depends(get_session),
    cache: redis.Redis = Depends(get_redis),
):
    return ok(
        generate_operation_advice(
            db,
            cache,
            customer_id=customer_id,
            manager=employee,
            direction=body.direction,
            now=_now(),
        )
    )


@review_router.post("/{advice_id}/release")
def release_operation_advice(
    advice_id: int,
    # 放行资质在服务端收紧：客户经理看得到这条建议，但放不了行（发起与放行是两件事）。
    employee: Employee = Depends(require_employee_role(ADVISOR)),
    db: Session = Depends(get_session),
    cache: redis.Redis = Depends(get_redis),
):
    return ok(
        release_advice(db, cache, advice_id=advice_id, advisor_id=employee.id, now=_now())
    )


@review_router.post("/{advice_id}/reject")
def reject_operation_advice(
    advice_id: int,
    body: OperationAdviceRejectRequest,
    employee: Employee = Depends(require_employee_role(ADVISOR)),
    db: Session = Depends(get_session),
    cache: redis.Redis = Depends(get_redis),
):
    return ok(
        reject_advice(
            db,
            cache,
            advice_id=advice_id,
            advisor_id=employee.id,
            reason=body.reason,
            now=_now(),
        )
    )
