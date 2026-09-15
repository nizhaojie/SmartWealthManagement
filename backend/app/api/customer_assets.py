from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth.dependencies import AuthContext, require_customer
from app.customer_assets.service import get_assets, list_transactions
from app.db.session import get_session
from app.http import ok

router = APIRouter(prefix="/api/customer/assets")


@router.get("")
def customer_assets(
    auth: AuthContext = Depends(require_customer),
    db: Session = Depends(get_session),
):
    return ok(get_assets(db, customer_id=auth.subject_id))


@router.get("/transactions")
def customer_transactions(
    auth: AuthContext = Depends(require_customer),
    db: Session = Depends(get_session),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    transaction_type: str | None = Query(default=None),
):
    return ok(
        list_transactions(
            db,
            customer_id=auth.subject_id,
            start_date=start_date,
            end_date=end_date,
            transaction_type=transaction_type,
        )
    )
