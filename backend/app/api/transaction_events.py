"""内部补录：风控专员替系统补写一笔交易事件的通道。

这条通道**不是**交易事件的常规入口——常规入口是客户侧的交易受理
（`app.api.customer_transactions`），客户自己的申购、赎回与转账都从那里进风控。
这里只用于修复数据与演示：它绕过适当性、起投金额与可用余额的校验（ADR-0018），
因此只对风控专员开放（ADR-0018、ADR-0009 的护栏 7），且补录必带经办员工——
客户自助发起的交易没有经办员工，这是分辨两者的唯一依据（`CONTEXT.md` 的「内部补录」）。

接口本身只做参数拼装，落库、广播、规则匹配与预警生成都在
`app.risk_monitoring.alerting` 里，顺序由那里保证——先落库，再广播，最后过规则引擎。
"""

from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.dependencies import require_employee_role
from app.auth.roles import RISK_OFFICER
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
    employee: Employee = Depends(require_employee_role(RISK_OFFICER)),
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
    # 内部补录必带产品，因此一定落在 fin_transaction 里（转账走客户侧受理，
    # 它有收款人信息，而这条路子没有）。
    assert transaction is not None
    return ok(
        {
            "transaction": alerting.transaction_response(transaction),
            "alerts": [alerting.alert_response(alert) for alert in alerts],
        }
    )
