"""资金账户余额的只读接口。

客户侧不接收客户标识：取谁的余额由凭证推导，请求体或查询串里的标识一概不作数。
内部侧沿用既有路径形状（`/api/internal/customers/{customer_id}/...`），可见范围
由 `app.customer_scope` 收紧——客户经理只看得到自己名下客户的余额。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.dependencies import AuthContext, current_employee, require_customer
from app.db.models import Employee
from app.db.session import get_session
from app.funding_account.service import ensure_can_view, get_available_balance
from app.http import ok

router = APIRouter(prefix="/api/customer/funding-account")
internal_router = APIRouter(prefix="/api/internal/customers")


@router.get("")
def customer_funding_account(
    auth: AuthContext = Depends(require_customer),
    db: Session = Depends(get_session),
):
    return ok(get_available_balance(db, customer_id=auth.subject_id))


@internal_router.get("/{customer_id}/funding-account")
def internal_funding_account(
    customer_id: int,
    employee: Employee = Depends(current_employee),
    db: Session = Depends(get_session),
):
    ensure_can_view(db, employee, customer_id)
    return ok(get_available_balance(db, customer_id=customer_id))
