"""工单接口：列表、详情、建单与三条流转路径。

写操作（建单、接单、办结、关闭）只放开给风控专员——它们是处置接口，处置人的身份
要落在留痕里，不能由任意角色代填。读操作对所有内部员工开放，但客户经理只看得到
自己名下客户的工单：理财顾问与客户经理要看得见状态，「看得见」不等于「看得见所有
人的」（`app.work_order.service`）。

流转拆成三个具名端点而不是一个带 `to_status` 的通用端点，是因为每种流转要求的东西
不同：办结必须给处置结论，关闭不必；通用端点会把这些差异藏进运行时分支。
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.dependencies import current_employee, require_employee_role
from app.auth.roles import RISK_OFFICER
from app.db.models import Employee
from app.db.session import get_session
from app.http import ok
from app.pagination import PageParams, page_params
from app.work_order import service

router = APIRouter(prefix="/api/internal/work-orders")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class ExternalWorkOrderRequest(BaseModel):
    order_type: str
    customer_id: int | None = None
    reason: str = ""


class TransitionRequest(BaseModel):
    reason: str = ""


class CompletionRequest(BaseModel):
    reason: str = ""
    conclusion: str = ""


@router.get("")
def list_work_orders(
    status: str | None = None,
    alert_id: int | None = None,
    customer_id: int | None = None,
    page: PageParams = Depends(page_params),
    employee: Employee = Depends(current_employee),
    db: Session = Depends(get_session),
):
    return ok(
        service.list_work_orders(
            db,
            employee=employee,
            page=page,
            status=status,
            alert_id=alert_id,
            customer_id=customer_id,
        )
    )


@router.get("/{work_order_id}")
def get_work_order(
    work_order_id: int,
    employee: Employee = Depends(current_employee),
    db: Session = Depends(get_session),
):
    return ok(service.detail(db, work_order_id, employee=employee))


@router.post("")
def create_work_order(
    body: ExternalWorkOrderRequest,
    db: Session = Depends(get_session),
    _employee: Employee = Depends(require_employee_role(RISK_OFFICER)),
):
    work_order = service.create_external(
        db,
        order_type=body.order_type,
        customer_id=body.customer_id,
        employee=_employee,
        reason=body.reason,
        now=_now(),
    )
    return ok(service.serialize(work_order, handler_name=_employee.real_name))


@router.post("/{work_order_id}/accept")
def accept_work_order(
    work_order_id: int,
    body: TransitionRequest,
    db: Session = Depends(get_session),
    _employee: Employee = Depends(require_employee_role(RISK_OFFICER)),
):
    work_order = service.accept(
        db, work_order_id=work_order_id, employee=_employee, reason=body.reason, now=_now()
    )
    return ok(service.serialize(work_order, handler_name=_employee.real_name))


@router.post("/{work_order_id}/complete")
def complete_work_order(
    work_order_id: int,
    body: CompletionRequest,
    db: Session = Depends(get_session),
    _employee: Employee = Depends(require_employee_role(RISK_OFFICER)),
):
    work_order = service.complete(
        db,
        work_order_id=work_order_id,
        employee=_employee,
        reason=body.reason,
        conclusion=body.conclusion,
        now=_now(),
    )
    return ok(service.serialize(work_order, handler_name=_employee.real_name))


@router.post("/{work_order_id}/close")
def close_work_order(
    work_order_id: int,
    body: CompletionRequest,
    db: Session = Depends(get_session),
    _employee: Employee = Depends(require_employee_role(RISK_OFFICER)),
):
    work_order = service.close(
        db,
        work_order_id=work_order_id,
        employee=_employee,
        reason=body.reason,
        conclusion=body.conclusion,
        now=_now(),
    )
    return ok(service.serialize(work_order, handler_name=_employee.real_name))
