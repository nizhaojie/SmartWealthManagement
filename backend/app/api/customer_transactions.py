"""客户侧的交易受理入口：申购、赎回、转账与充值。

客户标识由凭证推导，请求体里没有这个字段——塞进来的不作数。这里只做参数拼装：
校验、成交与持仓、可用余额的更新都在 `app.order_acceptance`，风控的接入在
`app.risk_monitoring.alerting`。

内部补录走的是另一个入口（`app.api.transaction_events`）：那条路子绕过本服务的校验，
因此只对风控专员开放（ADR-0018）。
"""

from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.dependencies import AuthContext, require_customer
from app.db.session import get_session
from app.event_bus import EventPublisher, get_event_publisher
from app.http import ok
from app.order_acceptance import service

router = APIRouter(prefix="/api/customer/transactions")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class PurchaseRequest(BaseModel):
    product_code: str
    amount: Decimal


class RedemptionRequest(BaseModel):
    product_code: str
    shares: Decimal


class TransferRequest(BaseModel):
    # 对手方是机构之外的收款人（ADR-0019），只有姓名与账号，没有产品。
    payee_name: str
    payee_account: str
    amount: Decimal


class DepositRequest(BaseModel):
    # 充值不记钱的来源（Q2）：没有付款人、没有渠道，只有金额。
    amount: Decimal


@router.post("/purchase")
def purchase(
    body: PurchaseRequest,
    auth: AuthContext = Depends(require_customer),
    db: Session = Depends(get_session),
    publisher: EventPublisher = Depends(get_event_publisher),
):
    return ok(
        service.purchase(
            db,
            publisher=publisher,
            customer_id=auth.subject_id,
            product_code=body.product_code,
            amount=body.amount,
            now=_now(),
        )
    )


@router.post("/redemption")
def redemption(
    body: RedemptionRequest,
    auth: AuthContext = Depends(require_customer),
    db: Session = Depends(get_session),
    publisher: EventPublisher = Depends(get_event_publisher),
):
    return ok(
        service.redeem(
            db,
            publisher=publisher,
            customer_id=auth.subject_id,
            product_code=body.product_code,
            shares=body.shares,
            now=_now(),
        )
    )


@router.post("/transfer")
def transfer(
    body: TransferRequest,
    auth: AuthContext = Depends(require_customer),
    db: Session = Depends(get_session),
    publisher: EventPublisher = Depends(get_event_publisher),
):
    return ok(
        service.transfer(
            db,
            publisher=publisher,
            customer_id=auth.subject_id,
            payee_name=body.payee_name,
            payee_account=body.payee_account,
            amount=body.amount,
            now=_now(),
        )
    )


@router.post("/deposit")
def deposit(
    body: DepositRequest,
    auth: AuthContext = Depends(require_customer),
    db: Session = Depends(get_session),
    publisher: EventPublisher = Depends(get_event_publisher),
):
    return ok(
        service.deposit(
            db,
            publisher=publisher,
            customer_id=auth.subject_id,
            amount=body.amount,
            now=_now(),
        )
    )
