"""客户可见视图中的资产：持仓与交易流水。

客户标识一律由调用方从身份推导后传入，本模块不接受任何来自请求体的客户标识。
"""

from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select

from app.db.models import Holding, Product, Transaction
from app.risk_assessment.service import find_current_result

HELD_STATUS = "持有中"
ZERO = Decimal("0.00")
CENTS = Decimal("0.01")


def _format_amount(value: Decimal | None) -> str:
    return format(value if value is not None else ZERO, "f")


def _serialize_holding(holding: Holding, product: Product) -> dict:
    return {
        "product_code": product.product_code,
        "product_name": product.product_name,
        "product_type": product.product_type,
        "product_risk_level": product.risk_level,
        "shares": _format_amount(holding.shares),
        "cost_amount": _format_amount(holding.cost_amount),
        "market_value": _format_amount(holding.current_value),
        "profit_loss": _format_amount(holding.profit_loss),
        "profit_ratio": _format_amount(holding.profit_ratio),
    }


def _serialize_transaction(transaction: Transaction, product: Product) -> dict:
    return {
        "transaction_no": transaction.transaction_no,
        "transaction_type": transaction.transaction_type,
        "product_code": product.product_code,
        "product_name": product.product_name,
        "amount": _format_amount(transaction.amount),
        "shares": _format_amount(transaction.shares),
        "nav": _format_amount(transaction.nav),
        "fee": _format_amount(transaction.fee),
        "status": transaction.status,
        "traded_at": transaction.create_time.isoformat(),
    }


def _risk_level_conclusion(db: Session, *, customer_id: int) -> tuple[str | None, str | None]:
    result = find_current_result(db, customer_id=customer_id)
    if result is None:
        return None, None
    return result["risk_level"], result["valid_until"]


def get_assets(db: Session, *, customer_id: int) -> dict:
    rows = db.execute(
        select(Holding, Product)
        .join(Product, Product.id == Holding.product_id)
        .where(Holding.customer_id == customer_id, Holding.status == HELD_STATUS)
        .order_by(Product.product_code.asc())
    ).all()

    total_market_value = sum((row[0].current_value or ZERO for row in rows), ZERO)
    risk_level, risk_level_valid_until = _risk_level_conclusion(db, customer_id=customer_id)

    return {
        "risk_level": risk_level,
        "risk_level_valid_until": risk_level_valid_until,
        "total_market_value": _format_amount(total_market_value.quantize(CENTS)),
        "holding_count": len(rows),
        "holdings": [_serialize_holding(holding, product) for holding, product in rows],
    }


def _apply_transaction_filters(
    stmt: Select,
    *,
    start_date: date | None,
    end_date: date | None,
    transaction_type: str | None,
) -> Select:
    if start_date is not None:
        stmt = stmt.where(Transaction.create_time >= datetime.combine(start_date, time.min))
    if end_date is not None:
        stmt = stmt.where(
            Transaction.create_time < datetime.combine(end_date + timedelta(days=1), time.min)
        )
    if transaction_type:
        stmt = stmt.where(Transaction.transaction_type == transaction_type)
    return stmt


def list_transactions(
    db: Session,
    *,
    customer_id: int,
    start_date: date | None = None,
    end_date: date | None = None,
    transaction_type: str | None = None,
) -> dict:
    stmt = (
        select(Transaction, Product)
        .join(Product, Product.id == Transaction.product_id)
        .where(Transaction.customer_id == customer_id)
    )
    stmt = _apply_transaction_filters(
        stmt, start_date=start_date, end_date=end_date, transaction_type=transaction_type
    )
    stmt = stmt.order_by(Transaction.create_time.desc(), Transaction.id.desc())

    rows = db.execute(stmt).all()
    return {"transactions": [_serialize_transaction(row, product) for row, product in rows]}
