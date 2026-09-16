from datetime import datetime, timezone

import redis
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.advisory.draft import get_draft, serialize_draft
from app.advisory.schemas import AdvisoryPlanRequest
from app.advisory.service import generate_advisory_plan
from app.auth.dependencies import require_employee_role
from app.auth.roles import ADVISOR
from app.db.models import Employee
from app.db.session import get_session
from app.http import ok
from app.redis_client import get_redis

router = APIRouter(prefix="/api/internal/advisory")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@router.post("/customers/{customer_id}/plan")
def generate_plan(
    customer_id: int,
    body: AdvisoryPlanRequest,
    # 只有理财顾问能发起生成：投顾助手 Agent 面向理财顾问，客户经理没有资质。
    employee: Employee = Depends(require_employee_role(ADVISOR)),
    db: Session = Depends(get_session),
    cache: redis.Redis = Depends(get_redis),
):
    draft = generate_advisory_plan(
        db, cache, customer_id=customer_id, advisor_id=employee.id, tilt=body.tilt, now=_now()
    )
    return ok(draft)


@router.get("/drafts/{draft_id}")
def get_advisory_draft(
    draft_id: int,
    # AI 原稿是投顾内容审核前的举证材料，读取权限与生成权限一致收紧到理财顾问。
    _employee: Employee = Depends(require_employee_role(ADVISOR)),
    db: Session = Depends(get_session),
):
    return ok(serialize_draft(get_draft(db, draft_id)))
