"""操作建议的可选项：一位客户在某个方向下能选哪些产品、每只的金额区间是多少。

候选池（`app.suitability.service.get_candidate_pool`）是与方向无关的合规事实；
这里把方向过滤与金额区间叠上去，回答的是发起表单要问的那个问题。两条选品规则
——申购 = 候选池 − 已持有、赎回 = 候选池 ∩ 已持有——**只在这里表达一次**：读取
端点渲染它，发起受理的校验要读同一份结果（`advice_options`），而不是另写一套。
在第二处再表达一遍（前端按方向过滤、受理另写一套区间判断）不会有断言失败，
漂移的表现是「下拉里有这只产品，一提交被拒」。

金额与份额的上下限走受理侧的成交口径（`app.order_acceptance.service.purchase_cost`），
不在这里另算费率：差一分钱，下拉里就会出现一条注定被受理拒绝的产品。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from decimal import ROUND_DOWN, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.customer_assets.service import list_holding_shares
from app.db.models import Product
from app.exceptions import AppError
from app.funding_account.service import get_available_balance_value
from app.order_acceptance.service import PERCENT, PURCHASE, REDEEM, purchase_cost
from app.suitability.service import get_candidate_pool

MONEY = Decimal("0.01")
ZERO = Decimal("0.00")

# 方向的合法取值与文案只有这一份：读取端点与发起受理都在这里判定（`advice_options`），
# 受理侧的两条分支也按它分叉。
ALLOWED_DIRECTIONS = (PURCHASE, REDEEM)
UNKNOWN_DIRECTION_MESSAGE = "未知的操作方向"

# 发起受理的拒绝文案。它们要说的是「**发起人选的不合法**」，不是「Agent 选不到」——
# 选品权移交之后（ADR-0021），失败的原因只可能来自提交上来的那份输入。
NO_CANDIDATE_MESSAGE = "所选产品不在该客户的可申购范围内"
NOT_ENOUGH_BALANCE_MESSAGE = "可用余额不足以支付这次申购的金额与手续费"
NO_HOLDING_MESSAGE = "所选产品不在该客户的可赎回持仓范围内"
BELOW_MIN_AMOUNT_MESSAGE = "申购金额低于该产品的起投金额"
INVALID_SHARES_MESSAGE = "赎回份额必须大于零且不超过当前持仓份额"
MISSING_AMOUNT_MESSAGE = "申购必须给出金额"
MISSING_SHARES_MESSAGE = "赎回必须给出份额"


def _product_rows(db: Session, product_codes: Sequence[str]) -> dict[str, Product]:
    """产品代码 → 产品行：起投金额、期限与费率都在行上，池里的摘要没有这些。"""
    rows = db.scalars(select(Product).where(Product.product_code.in_(product_codes))).all()
    return {row.product_code: row for row in rows}


def purchase_ceiling(product: Product, available_balance: Decimal) -> Decimal:
    """可用余额买得起的最大申购金额（受理侧口径）。

    反解 `purchase_cost` 而不是另写一遍费率：`cost(金额) = 金额 + 金额 × 费率`，费率
    是百分数（与产品披露的口径一致）。反解的结果先向下取整——向上取整会给出一个
    `purchase_cost` 大于余额的上限，前端把输入卡在它上面，每一条都会被受理拒绝。
    金额与手续费各自四舍五入，反解因此可能与真正的上限差一分，最后再补到那一分钱上。
    """
    rate = product.fee_rate / PERCENT
    ceiling = (available_balance / (1 + rate)).quantize(MONEY, rounding=ROUND_DOWN)
    while ceiling > ZERO and purchase_cost(product, ceiling) > available_balance:
        ceiling -= MONEY
    while purchase_cost(product, ceiling + MONEY) <= available_balance:
        ceiling += MONEY
    return ceiling


def product_elements(product: Product) -> dict:
    """选项文案的五要素：产品名 + 代码 + 风险等级 + 期限 + 起投金额（Q13）。

    两个方向的选项都先铺这一层，差别只在后面接的那个区间——前端渲染的是同一组字段，
    拼两遍的话，加一个要素时总有一边会被漏掉。理由（`app.operation_advice.reasons`）
    要引用的产品要素也在这一层里，图按产品代码加载后拿它当 `product`，不再另拼一份。
    """
    return {
        "product_code": product.product_code,
        "product_name": product.product_name,
        "product_type": product.product_type,
        "risk_level": product.risk_level,
        "term_days": product.term_days,
        "min_amount": product.min_amount,
    }


def _purchase_option(product: Product, available_balance: Decimal) -> dict:
    return {
        **product_elements(product),
        "max_amount": purchase_ceiling(product, available_balance),
        # 买不起的项**仍然列出**（前端禁用并注明原因）：藏掉会让经理以为候选池里少了一只，
        # 而那只正是他要拿来跟客户解释的东西。判定与受理同一处口径。
        "affordable": purchase_cost(product, product.min_amount) <= available_balance,
    }


def _redemption_option(product: Product, shares: Decimal) -> dict:
    return {
        **product_elements(product),
        # 赎回的区间是份额，不是金额：客户侧自助赎回本来就按份额填（可部分赎回）。
        "max_shares": shares,
        # 赎回没有余额门槛——卖出不需要先有钱。这个方向的「选项成立」就是有份额可卖：
        # 份额为零的持仓在上面已被方向资格滤掉，因此列出来的项一律是选得动的。
        "affordable": True,
    }


def advice_options(
    db: Session,
    *,
    customer_id: int,
    direction: str,
    now: datetime,
) -> list[dict]:
    """给定客户与方向，返回可选项：产品要素 + 该方向的金额/份额区间 + `affordable`。

    值一律是 `Decimal`（呈现层的字符串由 `serialize_advice_options` 负责），发起受理
    直接拿这里的数做校验——两个入口因此读的是同一份计算，而不是各算各的。
    """
    if direction not in ALLOWED_DIRECTIONS:
        raise AppError(400, UNKNOWN_DIRECTION_MESSAGE)

    pool = get_candidate_pool(db, customer_id=customer_id, now=now)
    pool_codes = [item["product_code"] for item in pool["products"]]
    held_shares = list_holding_shares(db, customer_id=customer_id)
    if direction == PURCHASE:
        eligible = [code for code in pool_codes if code not in held_shares]
    else:
        eligible = [code for code in pool_codes if held_shares.get(code, ZERO) > ZERO]
    if not eligible:
        return []

    # 资金账户两条方向都要读：赎回不花这笔钱，但受理赎回同样要求资金账户（成交金额要
    # 入账），缺账户时在这里就说出来，而不是给出一个一提交就失败的选项列表。
    available_balance = get_available_balance_value(db, customer_id=customer_id)
    rows = _product_rows(db, eligible)
    if direction == PURCHASE:
        return [_purchase_option(rows[code], available_balance) for code in eligible]
    return [_redemption_option(rows[code], held_shares[code]) for code in eligible]


def resolve_advice_choice(
    db: Session,
    *,
    customer_id: int,
    direction: str,
    product_code: str,
    amount: Decimal | None = None,
    shares: Decimal | None = None,
    now: datetime,
) -> tuple[dict, Decimal]:
    """受理发起人给的三个输入，返回「选项 + 选定的那个数」（金额或份额）。

    按 `product_code` 在 `advice_options` 的结果里找——读取端点与受理校验读的是同一份
    计算，选品规则不会因为多一个入口而漂移（ADR-0021 的主要实现约束）。找不到就是
    拒绝：候选池外的产品、已持有做申购、未持有做赎回，三种情况都落在「这个方向下没有
    这只产品」上，因此两条方向的文案各自只有一句。

    区间也直接用可选项里的两个数（`min_amount` / `max_amount`、`max_shares`）：它们是
    受理侧成交口径算出来的（`purchase_cost` / 持仓份额），在这里再算一遍费率就是第二套
    口径，而两套口径差一分钱的表现是「下拉里有这只产品，一提交被拒」。

    金额与份额二选一由方向决定，因此缺失是**发起人的输入错了**，不是请求体不成立。
    """
    options = advice_options(db, customer_id=customer_id, direction=direction, now=now)
    option = next(
        (item for item in options if item["product_code"] == product_code),
        None,
    )
    if option is None:
        raise AppError(
            400, NO_CANDIDATE_MESSAGE if direction == PURCHASE else NO_HOLDING_MESSAGE
        )

    if direction == PURCHASE:
        if amount is None:
            raise AppError(400, MISSING_AMOUNT_MESSAGE)
        if amount < option["min_amount"]:
            raise AppError(400, BELOW_MIN_AMOUNT_MESSAGE)
        if amount > option["max_amount"]:
            # 上限就是「再添一分钱就买不起」的那一分钱：超了它必然付不起金额与手续费。
            raise AppError(400, NOT_ENOUGH_BALANCE_MESSAGE)
        return option, amount

    if shares is None:
        raise AppError(400, MISSING_SHARES_MESSAGE)
    if shares <= ZERO or shares > option["max_shares"]:
        raise AppError(400, INVALID_SHARES_MESSAGE)
    return option, shares


def _serialize_option(option: dict, direction: str) -> dict:
    """可选项的呈现形状：金额与其余金额字段同口径，是字符串。

    不适用于该方向的那一项**不出现**，而不是给一个空值：赎回写 `max_amount` 是在陈述
    一个不存在的事实（与 `app.customer_assets.service._format_optional` 同一条口径）。
    """
    if direction == PURCHASE:
        upper = {"max_amount": format(option["max_amount"], "f")}
    else:
        upper = {"max_shares": format(option["max_shares"], "f")}
    return {
        "product_code": option["product_code"],
        "product_name": option["product_name"],
        "product_type": option["product_type"],
        "risk_level": option["risk_level"],
        "term_days": option["term_days"],
        "min_amount": format(option["min_amount"], "f"),
        **upper,
        "affordable": option["affordable"],
    }


def serialize_advice_options(direction: str, options: Sequence[dict]) -> dict:
    return {
        "direction": direction,
        "products": [_serialize_option(row, direction) for row in options],
    }
