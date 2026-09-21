"""客户经理的发起入口：为客户生成一条操作建议原稿。

`CONTEXT.md`「客户经理」：可以为名下客户发起操作建议——它只发起，放行是理财顾问的
事。因此这条路由只对客户经理开放，且只对名下客户（归属校验在 `app.operation_advice`）。
生成本身在业务操作 Agent 里，这里只做参数拼装。
"""

from datetime import datetime, timezone

import redis
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.dependencies import require_employee_role
from app.auth.roles import ACCOUNT_MANAGER
from app.db.models import Employee
from app.db.session import get_session
from app.http import ok
from app.operation_advice.schemas import OperationAdviceRequest
from app.operation_advice.service import generate_operation_advice
from app.redis_client import get_redis

router = APIRouter(prefix="/api/internal/customers")


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
