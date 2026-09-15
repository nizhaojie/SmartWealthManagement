from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select

from app.db.models import Product
from app.exceptions import AppError
from app.suitability.service import resolve_allowed_product_risk_levels

PRODUCT_NOT_FOUND_MESSAGE = "产品不存在"


def _serialize_product(product: Product) -> dict:
    return {
        "product_code": product.product_code,
        "product_name": product.product_name,
        "product_type": product.product_type,
        "risk_level": product.risk_level,
        "expected_return": format(product.expected_return, "f"),
        "min_amount": format(product.min_amount, "f"),
        "term_days": product.term_days,
        "fund_manager": product.fund_manager,
        "fee_rate": format(product.fee_rate, "f"),
        "status": product.status,
    }


def _apply_objective_filters(
    stmt: Select,
    *,
    product_type: str | None,
    risk_level: str | None,
    min_amount: Decimal | None,
    min_expected_return: Decimal | None,
    max_term_days: int | None,
) -> Select:
    if product_type:
        stmt = stmt.where(Product.product_type == product_type)
    if risk_level:
        stmt = stmt.where(Product.risk_level == risk_level)
    if min_amount is not None:
        stmt = stmt.where(Product.min_amount <= min_amount)
    if min_expected_return is not None:
        stmt = stmt.where(Product.expected_return >= min_expected_return)
    if max_term_days is not None:
        stmt = stmt.where(Product.term_days <= max_term_days)
    return stmt


def list_products(
    db: Session,
    *,
    customer_id: int,
    now: datetime,
    product_type: str | None = None,
    risk_level: str | None = None,
    min_amount: Decimal | None = None,
    min_expected_return: Decimal | None = None,
    max_term_days: int | None = None,
) -> dict:
    allowed = resolve_allowed_product_risk_levels(db, customer_id=customer_id, now=now)
    products: list[Product] = []
    if allowed:
        stmt = (
            select(Product)
            .where(Product.risk_level.in_(allowed), Product.status == "在售")
            .order_by(Product.product_code.asc())
        )
        stmt = _apply_objective_filters(
            stmt,
            product_type=product_type,
            risk_level=risk_level,
            min_amount=min_amount,
            min_expected_return=min_expected_return,
            max_term_days=max_term_days,
        )
        products = list(db.scalars(stmt).all())
    return {"products": [_serialize_product(row) for row in products]}


def get_product(db: Session, *, customer_id: int, product_code: str, now: datetime) -> dict:
    allowed = resolve_allowed_product_risk_levels(db, customer_id=customer_id, now=now)
    product = db.scalar(
        select(Product).where(Product.product_code == product_code, Product.status == "在售")
    )
    if product is None or product.risk_level not in allowed:
        raise AppError(404, PRODUCT_NOT_FOUND_MESSAGE)
    return _serialize_product(product)
