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
from app.customer_profile.calibration import recalibrate
from app.customer_profile.confidence import SOURCE_ADVISOR
from app.customer_profile.rerank import DEFAULT_SCENARIO_WEIGHTS, UNKNOWN_SCENARIO_MESSAGE
from app.customer_profile.schemas import WriteTagRequest
from app.customer_profile.service import get_internal_profile, list_customers, write_tag
from app.customer_scope import restrict_to_own_customers
from app.db.models import Employee
from app.db.session import get_session
from app.exceptions import AppError
from app.http import ok
from app.pagination import PageParams, page_params
from app.redis_client import get_redis
from app.risk_assessment.service import get_current_result
from app.settings import Settings, get_settings

router = APIRouter(prefix="/api/customer/profile")
internal_router = APIRouter(prefix="/api/internal/customers")
calibration_router = APIRouter(prefix="/api/internal/profiles")


@internal_router.get("")
def internal_list_customers(
    employee: Employee = Depends(current_employee),
    db: Session = Depends(get_session),
    page: PageParams = Depends(page_params),
    keyword: str | None = None,
):
    # 客户经理只看得到自己名下客户（app.customer_scope）；理财顾问与风控
    # 专员不受限，拿到全量目录。
    manager_id = employee.id if restrict_to_own_customers(employee) else None
    return ok(list_customers(db, manager_id=manager_id, keyword=keyword, page=page))


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
    scenario: str | None = None,
    query: str | None = None,
    _auth: AuthContext = Depends(require_internal),
    db: Session = Depends(get_session),
    cache=Depends(get_redis),
    settings: Settings = Depends(get_settings),
):
    if scenario is not None and scenario not in DEFAULT_SCENARIO_WEIGHTS:
        raise AppError(400, UNKNOWN_SCENARIO_MESSAGE)
    return ok(
        get_internal_profile(
            db,
            cache,
            customer_id=customer_id,
            now=_now(),
            scenario=scenario,
            query=query,
            weights_overrides=settings.confidence_rerank_weights,
        )
    )


@calibration_router.post("/calibrate")
def calibrate_profiles(
    _auth: AuthContext = Depends(require_internal),
    db: Session = Depends(get_session),
    cache=Depends(get_redis),
    settings: Settings = Depends(get_settings),
):
    now = _now()
    return ok(
        recalibrate(
            db,
            cache=cache,
            now=now,
            expiry_threshold=settings.profile_tag_expiry_threshold,
        )
    )


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
