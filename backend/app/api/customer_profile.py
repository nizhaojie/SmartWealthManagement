from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.dependencies import (
    ROLE_FORBIDDEN_MESSAGE,
    AuthContext,
    current_employee,
    require_customer,
    require_internal,
)
from app.auth.roles import ADVISOR
from app.customer_profile.confidence import SOURCE_ADVISOR
from app.customer_profile.schemas import WriteTagRequest
from app.customer_profile.service import get_internal_profile, list_customers, write_tag
from app.db.models import Employee
from app.db.session import get_session
from app.exceptions import AppError
from app.http import ok
from app.redis_client import get_redis
from app.risk_assessment.service import get_current_result

router = APIRouter(prefix="/api/customer/profile")
internal_router = APIRouter(prefix="/api/internal/customers")


@internal_router.get("")
def internal_list_customers(
    _auth: AuthContext = Depends(require_internal),
    db: Session = Depends(get_session),
):
    return ok(list_customers(db))


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@router.get("")
def customer_profile(
    auth: AuthContext = Depends(require_customer),
    db: Session = Depends(get_session),
):
    return ok(get_current_result(db, customer_id=auth.subject_id))


@internal_router.get("/{customer_id}/profile")
def internal_get_profile(
    customer_id: int,
    _auth: AuthContext = Depends(require_internal),
    db: Session = Depends(get_session),
    cache=Depends(get_redis),
):
    return ok(get_internal_profile(db, cache, customer_id=customer_id, now=_now()))


@internal_router.put("/{customer_id}/profile/tags")
def internal_write_tag(
    customer_id: int,
    body: WriteTagRequest,
    employee: Employee = Depends(current_employee),
    db: Session = Depends(get_session),
    cache=Depends(get_redis),
):
    if body.source == SOURCE_ADVISOR and employee.employee_role != ADVISOR:
        raise AppError(403, ROLE_FORBIDDEN_MESSAGE)
    now = _now()
    write_tag(
        db,
        cache,
        customer_id=customer_id,
        tag_key=body.tag_key,
        value=body.value,
        source=body.source,
        now=now,
        reason=body.reason,
    )
    return ok(get_internal_profile(db, cache, customer_id=customer_id, now=now))
