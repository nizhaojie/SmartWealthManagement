"""交易事件提交：风控监测链路的入口。

交易事件由接口提交（实时流式接入不在本 slice 范围内）。接口本身只做参数拼装，
落库、广播、规则匹配与预警生成都在 `app.risk_monitoring.alerting` 里，顺序由那里
保证——先落库，再广播，最后过规则引擎。
"""

from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.dependencies import current_employee
from app.db.models import Employee
from app.db.session import get_session
from app.event_bus import EventPublisher, get_event_publisher
from app.http import ok
from app.risk_monitoring import alerting

router = APIRouter(prefix="/api/internal/transaction-events")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class TransactionEventRequest(BaseModel):
    customer_id: int
    product_id: int
    transaction_type: str
    amount: Decimal
    # 不传时按提交时刻落库；由外部系统回放历史交易时带上真实发生时间。
    occurred_at: datetime | None = None
    # 不传时由系统生成。外部系统自带流水号时传进来，重复即拒绝。
    transaction_no: str | None = None
    shares: Decimal = Decimal("0")
    nav: Decimal = Decimal("0")
    fee: Decimal = Decimal("0")


@router.post("")
def submit_transaction_event(
    body: TransactionEventRequest,
    db: Session = Depends(get_session),
    publisher: EventPublisher = Depends(get_event_publisher),
    employee: Employee = Depends(current_employee),
):
    now = _now()
    transaction, alerts = alerting.submit_transaction_event(
        db,
        publisher=publisher,
        submission=alerting.TransactionSubmission(
            customer_id=body.customer_id,
            product_id=body.product_id,
            transaction_type=body.transaction_type,
            amount=body.amount,
            occurred_at=body.occurred_at or now,
            shares=body.shares,
            nav=body.nav,
            fee=body.fee,
            transaction_no=body.transaction_no,
        ),
        operator_id=employee.id,
        now=now,
    )
    return ok(
        {
            "transaction": alerting.transaction_response(transaction),
            "alerts": [alerting.alert_response(alert) for alert in alerts],
        }
    )
