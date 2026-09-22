"""客户可见视图中的资产：持仓。

客户标识一律由调用方从身份推导后传入，本模块不接受任何来自请求体的客户标识。
"""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Holding, Product
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


def _risk_level_conclusion(db: Session, *, customer_id: int) -> tuple[str | None, str | None]:
    result = find_current_result(db, customer_id=customer_id)
    if result is None:
        return None, None
    return result["risk_level"], result["valid_until"]


def list_holding_shares(db: Session, *, customer_id: int) -> dict[str, Decimal]:
    """持仓产品代码 → 份额（只含「持有中」）。

    赎回建议要按份额算成交金额，因此需要数值形式；呈现用的份额字符串由
    `get_assets` 负责，两者读的是同一批行。
    """
    rows = db.execute(
        select(Product.product_code, Holding.shares)
        .join(Product, Product.id == Holding.product_id)
        .where(Holding.customer_id == customer_id, Holding.status == HELD_STATUS)
    ).all()
    return {product_code: shares for product_code, shares in rows}


def list_held_product_codes(db: Session, *, customer_id: int) -> set[str]:
    return set(list_holding_shares(db, customer_id=customer_id))


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
