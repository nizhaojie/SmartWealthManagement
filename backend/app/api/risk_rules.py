from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import AuthContext, require_employee_role, require_internal
from app.auth.roles import RISK_OFFICER
from app.db.models import Employee
from app.db.session import get_session
from app.http import ok
from app.pagination import PageParams, page_params, paginated_response
from app.risk_monitoring import service

router = APIRouter(prefix="/api/internal/risk-rules")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class EnabledUpdateRequest(BaseModel):
    enabled: bool
    reason: str = ""


class ThresholdUpdateRequest(BaseModel):
    threshold: dict
    reason: str = ""


@router.get("")
def list_risk_rules(
    page: PageParams = Depends(page_params),
    db: Session = Depends(get_session),
    _auth: AuthContext = Depends(require_internal),
):
    rules, total = service.list_rules(db, page=page)
    return ok(
        paginated_response(
            [service.rule_response(rule) for rule in rules], total=total, params=page
        )
    )


@router.get("/{rule_id}/changes")
def list_risk_rule_changes(
    rule_id: int,
    db: Session = Depends(get_session),
    _auth: AuthContext = Depends(require_internal),
):
    rule = service.get_rule(db, rule_id)
    changes = service.list_rule_changes(db, rule_id)
    changed_by_ids = {change.changed_by for change in changes}
    names = {
        employee.id: employee.real_name
        for employee in db.scalars(select(Employee).where(Employee.id.in_(changed_by_ids))).all()
    }
    return ok(
        [
            service.change_response(
                change, rule_code=rule.rule_code, changed_by_name=names.get(change.changed_by, "")
            )
            for change in changes
        ]
    )


@router.patch("/{rule_id}/enabled")
def update_risk_rule_enabled(
    rule_id: int,
    body: EnabledUpdateRequest,
    db: Session = Depends(get_session),
    _employee: Employee = Depends(require_employee_role(RISK_OFFICER)),
):
    rule = service.set_rule_enabled(
        db,
        rule_id=rule_id,
        enabled=body.enabled,
        employee=_employee,
        reason=body.reason,
        now=_now(),
    )
    return ok(service.rule_response(rule))


@router.patch("/{rule_id}/threshold")
def update_risk_rule_threshold(
    rule_id: int,
    body: ThresholdUpdateRequest,
    db: Session = Depends(get_session),
    _employee: Employee = Depends(require_employee_role(RISK_OFFICER)),
):
    rule = service.update_rule_threshold(
        db,
        rule_id=rule_id,
        threshold=body.threshold,
        employee=_employee,
        reason=body.reason,
        now=_now(),
    )
    return ok(service.rule_response(rule))
