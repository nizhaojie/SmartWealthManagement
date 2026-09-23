from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.advisory.access import ensure_can_view
from app.auth.dependencies import AuthContext, current_employee, require_customer
from app.customer_assets.look_through import look_through
from app.customer_assets.service import get_assets
from app.db.models import Employee
from app.db.session import get_session
from app.http import ok

router = APIRouter(prefix="/api/customer/assets")
internal_router = APIRouter(prefix="/api/internal/customers")


@internal_router.get("/{customer_id}/assets")
def internal_customer_assets(
    customer_id: int,
    employee: Employee = Depends(current_employee),
    db: Session = Depends(get_session),
):
    # 客户标识来自路径，只做 require_internal 的话，客户经理按 id 拼一个 URL 就能
    # 读到非名下客户的持仓——前端没给入口不构成约束。可见范围与资金账户同一口径
    # （app.customer_scope）；理财顾问与风控专员不受限。
    ensure_can_view(db, employee, customer_id)
    return ok(get_assets(db, customer_id=customer_id))


@router.get("")
def customer_assets(
    auth: AuthContext = Depends(require_customer),
    db: Session = Depends(get_session),
):
    return ok(get_assets(db, customer_id=auth.subject_id))


@router.get("/holdings/{product_code}/look-through")
def customer_holding_look_through(
    product_code: str,
    auth: AuthContext = Depends(require_customer),
    db: Session = Depends(get_session),
):
    return ok(look_through(db, customer_id=auth.subject_id, product_code=product_code))
