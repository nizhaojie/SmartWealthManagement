from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth.dependencies import AuthContext, require_customer
from app.db.session import get_session
from app.http import ok
from app.pagination import PageParams, page_params
from app.product_screening.service import get_product, list_products

router = APIRouter(prefix="/api/customer/products")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@router.get("")
def customer_products(
    auth: AuthContext = Depends(require_customer),
    db: Session = Depends(get_session),
    page: PageParams = Depends(page_params),
    product_type: str | None = None,
    risk_level: str | None = None,
    min_amount: Decimal | None = Query(default=None),
    min_expected_return: Decimal | None = Query(default=None),
    max_term_days: int | None = None,
):
    return ok(
        list_products(
            db,
            customer_id=auth.subject_id,
            now=_now(),
            page=page,
            product_type=product_type,
            risk_level=risk_level,
            min_amount=min_amount,
            min_expected_return=min_expected_return,
            max_term_days=max_term_days,
        )
    )


@router.get("/{product_code}")
def customer_product_detail(
    product_code: str,
    auth: AuthContext = Depends(require_customer),
    db: Session = Depends(get_session),
):
    return ok(
        get_product(
            db,
            customer_id=auth.subject_id,
            product_code=product_code,
            now=_now(),
        )
    )
