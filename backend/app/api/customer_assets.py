from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.dependencies import AuthContext, require_customer, require_internal
from app.customer_assets.look_through import look_through
from app.customer_assets.service import get_assets
from app.db.session import get_session
from app.http import ok

router = APIRouter(prefix="/api/customer/assets")
internal_router = APIRouter(prefix="/api/internal/customers")


@internal_router.get("/{customer_id}/assets")
def internal_customer_assets(
    customer_id: int,
    _auth: AuthContext = Depends(require_internal),
    db: Session = Depends(get_session),
):
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
