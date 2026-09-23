"""预警的读取与处置入口：列表、详情、排除、升级，以及从预警派生工单。

三个写操作都收在风控专员手里，也都要求非空理由——预警的关闭与升级由人做出并
留下署名，系统不做这件事（`app.risk_monitoring.alert_status`）。读操作对所有内部
员工开放，但客户经理只看得到自己名下客户的预警（`app.risk_monitoring.alert_service`）。
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.dependencies import current_employee, require_employee_role
from app.auth.roles import RISK_OFFICER
from app.db.models import Employee, RiskAlert
from app.db.session import get_session
from app.http import ok
from app.pagination import PageParams, page_params
from app.risk_monitoring import alert_service, alerting, disposition
from app.risk_monitoring.alert_service import AlertOrder
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


@router.get("")
def list_risk_alerts(
    alert_level: str | None = None,
    status: str | None = None,
    customer_id: int | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    order_by: AlertOrder = Query(default="created_desc", description="排序方式"),
    page: PageParams = Depends(page_params),
    employee: Employee = Depends(current_employee),
    db: Session = Depends(get_session),
):
    return ok(
        alert_service.list_alerts(
            db,
            employee=employee,
            page=page,
            alert_level=alert_level,
            status=status,
            customer_id=customer_id,
            created_from=created_from,
            created_to=created_to,
            order_by=order_by,
        )
    )


@router.get("/{alert_id}")
def get_risk_alert(
    alert_id: int,
    employee: Employee = Depends(current_employee),
    db: Session = Depends(get_session),
):
    return ok(alert_service.detail(db, alert_id, employee=employee))


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
