"""预警自身的处置入口：排除、升级，以及从预警派生工单。

三个写操作都收在风控专员手里，也都要求非空理由——预警的关闭与升级由人做出并
留下署名，系统不做这件事（`app.risk_monitoring.alert_status`）。
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.dependencies import require_employee_role
from app.auth.roles import RISK_OFFICER
from app.db.models import Employee, RiskAlert
from app.db.session import get_session
from app.http import ok
from app.risk_monitoring import alerting, disposition
from app.work_order import service as work_orders

router = APIRouter(prefix="/api/internal/risk-alerts")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class DispositionRequest(BaseModel):
    reason: str = ""


class DeriveWorkOrderRequest(BaseModel):
    reason: str = ""


def _disposition_response(alert: RiskAlert, employee: Employee) -> dict:
    return {**alerting.alert_response(alert), "handled_by_name": employee.real_name}


@router.post("/{alert_id}/exclude")
def exclude_alert(
    alert_id: int,
    body: DispositionRequest,
    db: Session = Depends(get_session),
    _employee: Employee = Depends(require_employee_role(RISK_OFFICER)),
):
    alert = disposition.exclude_alert(
        db, alert_id=alert_id, employee=_employee, reason=body.reason, now=_now()
    )
    return ok(_disposition_response(alert, _employee))


@router.post("/{alert_id}/escalate")
def escalate_alert(
    alert_id: int,
    body: DispositionRequest,
    db: Session = Depends(get_session),
    _employee: Employee = Depends(require_employee_role(RISK_OFFICER)),
):
    alert = disposition.escalate_alert(
        db, alert_id=alert_id, employee=_employee, reason=body.reason, now=_now()
    )
    return ok(_disposition_response(alert, _employee))


@router.post("/{alert_id}/work-orders")
def derive_work_order(
    alert_id: int,
    body: DeriveWorkOrderRequest,
    db: Session = Depends(get_session),
    _employee: Employee = Depends(require_employee_role(RISK_OFFICER)),
):
    work_order = work_orders.derive_from_alert(
        db, alert_id=alert_id, employee=_employee, reason=body.reason, now=_now()
    )
    return ok(work_orders.serialize(work_order, handler_name=_employee.real_name))
