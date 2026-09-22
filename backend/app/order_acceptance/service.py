"""客户侧的交易受理：申购、赎回与转账。

业务校验放在这里、放在落库之前（ADR-0018）。风控的交易事件入海口
（`app.risk_monitoring.alerting.submit_transaction_event`）是**既成事实**的输入，
不承载适当性与可用余额的判断——把它夹住，内部补录就没法修复一笔越级或超额的交易，
而那是它存在的理由。校验因此属于受理，不属于入海口。

校验集（spec Q11）：

| 校验 | 拒绝时的语义 |
|---|---|
| 产品在售 | 产品不在售 |
| 提交过风险测评 | 「请先完成风险测评」——不是「风险等级不足」 |
| 适当性：产品风险等级不高于风险承受等级 | 越级拒绝 |
| 申购金额不低于起投金额 | 低于产品起投金额 |
| 可用余额足够（申购含手续费） | 拒绝，并给出还差多少 |
| 赎回份额不超过持仓份额 | 拒绝 |

转账是同一套受理里的另一条路径，但它没有产品，因此适当性、起投金额与产品状态三条
不适用：校验只剩金额为正、收款人姓名与账号非空、可用余额足够。它的事实落在自己的表
`fin_transfer` 里（ADR-0019），但一样是一笔交易事件，一样从**同一个**入海口进风控
（`alerting.submit_transaction_event`，产品为空的那条分支）。

风评的判定**只看有没有测评记录，不看有效期**（Q18）：开户时写下的等级是占位而不是
结论，拿它去拒绝客户，客户会收到一个他无法理解的拒绝；而种子客户的风评 `valid_until`
全部停在多年以前，把过期也算进去会一次性锁死所有人。风评过期只做提示——过期怎么办
是全系统的问题，不该由这条需求顺手改掉。这也是这里不用
`app.suitability.service.resolve_allowed_product_risk_levels` 的原因：那个函数把过期
当作熔断，口径与本条需求正好相反。

成交口径：申购 `份额 = 金额 / 净值`、`手续费 = 金额 × 费率`、可用余额扣减 `金额 + 手续费`；
赎回 `成交金额 = 份额 × 净值`、`手续费 = 成交金额 × 费率`、可用余额增加 `成交金额 - 手续费`。
**持仓的当前市值仍是独立维护的字段**，不写成 `份额 × 净值` 的推导值（Q12）——没有净值时间
序列，改成推导等于顺手重写了资产页与穿透的所有数字。

交易的来源**不加字段**（Q22）：客户自助发起的交易没有经办员工（`operator_id` 为空），
内部补录的必带。分辨两者的唯一依据就是这个，`CONTEXT.md` 的「内部补录」记着它。
"""

from __future__ import annotations

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.customer_assets.service import (
    DEPOSIT,
    HELD_STATUS,
    TRANSFER,
    serialize_deposit,
    serialize_transaction,
    serialize_transfer,
)
from app.db.models import (
    Deposit,
    FundingAccount,
    Holding,
    Product,
    Transaction,
    Transfer,
)
from app.event_bus import EventPublisher
from app.exceptions import AppError
from app.risk_assessment.service import find_current_result
from app.risk_monitoring import alerting
from app.suitability.rules import allowed_product_risk_levels

PURCHASE = "申购"
REDEEM = "赎回"

ON_SALE = "在售"
# 份额归零的持仓不再参与资产页与穿透，因此不再是「持有中」。
CLEARED_STATUS = "已清仓"

MONEY = Decimal("0.01")
SHARE = Decimal("0.0001")
ZERO = Decimal("0.00")
PERCENT = Decimal("100")

PRODUCT_NOT_FOUND_MESSAGE = "产品不存在"
PRODUCT_NOT_ON_SALE_MESSAGE = "产品不在售"
ACCOUNT_MISSING_MESSAGE = "资金账户不存在"
ASSESSMENT_REQUIRED_MESSAGE = "请先完成风险测评"
OVERGRADE_MESSAGE = "产品风险等级高于你的风险承受等级"
NON_POSITIVE_AMOUNT_MESSAGE = "交易金额必须大于零"
NON_POSITIVE_SHARES_MESSAGE = "赎回份额必须大于零"
HOLDING_MISSING_MESSAGE = "没有可赎回的持仓"
NOT_ENOUGH_SHARES_MESSAGE = "赎回份额超过持仓份额"
MISSING_PAYEE_NAME_MESSAGE = "收款人姓名不能为空"
MISSING_PAYEE_ACCOUNT_MESSAGE = "收款人账号不能为空"

# 转账、充值流水号与交易流水号同一形状、不同前缀：多类记录会并排出现在客户的同一个列表里。
TRANSFER_NO_PREFIX = "TR"
DEPOSIT_NO_PREFIX = "DP"


def _money(value: Decimal) -> Decimal:
    return value.quantize(MONEY, rounding=ROUND_HALF_UP)


def _share(value: Decimal) -> Decimal:
    return value.quantize(SHARE, rounding=ROUND_HALF_UP)


def _fee(amount: Decimal, fee_rate: Decimal) -> Decimal:
    """手续费按费率计，费率是百分数（`0.2500` 即 0.25%），与产品的披露口径一致。"""
    return _money(amount * fee_rate / PERCENT)


def purchase_cost(product: Product, amount: Decimal) -> Decimal:
    """申购的全部支出：金额 + 手续费。

    公开出来是因为成交口径只有一处：业务操作 Agent 判断一条建议买不买得起时
    用的也是这个数，自己再算一遍费率迟早与受理侧漂移（差一分钱，建议就成了
    一条当场会被拒绝的建议）。
    """
    return amount + _fee(amount, product.fee_rate)


def redemption_amount(product: Product, shares: Decimal) -> Decimal:
    """赎回的成交金额（毛额）：份额 × 净值。入账金额再扣手续费，口径同此一处。"""
    return _money(shares * product.nav)


def _refresh_profit(holding: Holding) -> None:
    """盈亏两列随份额与成本的变动同步重算，但仍然是存在表里的字段。"""
    profit = _money(holding.current_value - holding.cost_amount)
    holding.profit_loss = profit
    holding.profit_ratio = (
        _share(profit / holding.cost_amount * PERCENT) if holding.cost_amount > 0 else ZERO
    )


def _require_product(db: Session, product_code: str) -> Product:
    product = db.scalar(select(Product).where(Product.product_code == product_code))
    if product is None:
        raise AppError(404, PRODUCT_NOT_FOUND_MESSAGE)
    if product.status != ON_SALE:
        # 产品清单里看不到它，是「筛选」；客户指名要买它，是「拒绝」，要说清楚原因。
        raise AppError(400, PRODUCT_NOT_ON_SALE_MESSAGE)
    return product


def _require_suitability(db: Session, *, customer_id: int, product: Product) -> None:
    result = find_current_result(db, customer_id=customer_id)
    if result is None:
        raise AppError(403, ASSESSMENT_REQUIRED_MESSAGE)
    if product.risk_level not in allowed_product_risk_levels(result["risk_level"]):
        raise AppError(403, OVERGRADE_MESSAGE)


def _require_account(db: Session, *, customer_id: int) -> FundingAccount:
    account = db.scalar(
        select(FundingAccount).where(FundingAccount.customer_id == customer_id)
    )
    if account is None:
        raise AppError(404, ACCOUNT_MISSING_MESSAGE)
    return account


def _require_min_amount(product: Product, amount: Decimal) -> None:
    if amount < product.min_amount:
        raise AppError(400, f"低于产品起投金额 {product.min_amount} 元")


def _require_balance(account: FundingAccount, cost: Decimal) -> None:
    if account.available_balance < cost:
        shortfall = _money(cost - account.available_balance)
        raise AppError(400, f"可用余额不足，还差 {shortfall} 元")


def _find_holding(db: Session, *, customer_id: int, product_id: int) -> Holding | None:
    return db.scalar(
        select(Holding).where(
            Holding.customer_id == customer_id,
            Holding.product_id == product_id,
        )
    )


def _submit(
    db: Session,
    *,
    publisher: EventPublisher,
    customer_id: int,
    product: Product,
    transaction_type: str,
    amount: Decimal,
    shares: Decimal,
    fee: Decimal,
    now: datetime,
) -> Transaction:
    """成交：交易落库 → 广播 → 过规则引擎，三条路径只有这一条。

    客户自助发起，因此 `operator_id` 为空（Q22）。落库由 `submit_transaction_event`
    提交，受理侧对可用余额与持仓的改动此刻还在同一个会话里，于是「成交」与「钱和份额的
    变动」在同一次提交中发生。
    """
    transaction, _alerts = alerting.submit_transaction_event(
        db,
        publisher=publisher,
        submission=alerting.TransactionSubmission(
            customer_id=customer_id,
            product_id=product.id,
            transaction_type=transaction_type,
            amount=amount,
            occurred_at=now,
            shares=shares,
            nav=product.nav,
            fee=fee,
        ),
        operator_id=None,
        now=now,
    )
    return transaction


def _apply_purchase(
    db: Session,
    *,
    customer_id: int,
    product: Product,
    shares: Decimal,
    amount: Decimal,
    now: datetime,
) -> None:
    holding = _find_holding(db, customer_id=customer_id, product_id=product.id)
    if holding is None:
        holding = Holding(
            customer_id=customer_id,
            product_id=product.id,
            shares=ZERO,
            cost_amount=ZERO,
            current_value=ZERO,
            profit_loss=ZERO,
            profit_ratio=ZERO,
            status=HELD_STATUS,
            create_time=now,
        )
        db.add(holding)
    elif holding.status != HELD_STATUS:
        # 清仓过的持仓又买了回来：份额、成本与市值都从零重新起算。
        holding.shares = ZERO
        holding.cost_amount = ZERO
        holding.current_value = ZERO
        holding.status = HELD_STATUS

    holding.shares = holding.shares + shares
    # 成本与市值都按**投入金额**增加（净值就是当前净值），因此买入那一刻盈亏为零；
    # 手续费不进成本——成本是投入本金，手续费在流水里单列一行。市值是独立维护的字段，
    # 不写成 `份额 × 净值`。
    holding.cost_amount = holding.cost_amount + amount
    holding.current_value = holding.current_value + amount
    _refresh_profit(holding)


def _apply_redemption(holding: Holding, *, shares: Decimal) -> None:
    remaining = holding.shares - shares
    if remaining == ZERO:
        # 份额归零：状态不再是「持有中」，资产页与穿透都不再看到它。
        holding.shares = ZERO
        holding.cost_amount = ZERO
        holding.current_value = ZERO
        holding.profit_loss = ZERO
        holding.profit_ratio = ZERO
        holding.status = CLEARED_STATUS
        return

    # 部分赎回按份额比例同时减持成本与市值——两者的比例保持不变，盈亏比例因此不变。
    ratio = shares / holding.shares
    holding.shares = remaining
    holding.cost_amount = _money(holding.cost_amount - _money(holding.cost_amount * ratio))
    holding.current_value = _money(holding.current_value - _money(holding.current_value * ratio))
    _refresh_profit(holding)


def _trade_result(
    transaction: Transaction, product: Product, account: FundingAccount
) -> dict:
    """受理结果：成交那一笔的完整流水，加上成交之后的可用余额。"""
    return {
        "transaction": serialize_transaction(transaction, product),
        "available_balance": format(account.available_balance, "f"),
    }


def purchase(
    db: Session,
    *,
    publisher: EventPublisher,
    customer_id: int,
    product_code: str,
    amount: Decimal,
    now: datetime,
) -> dict:
    """申购：校验通过后当场成交，并同步更新持仓与可用余额。"""
    if amount <= 0:
        raise AppError(400, NON_POSITIVE_AMOUNT_MESSAGE)
    product = _require_product(db, product_code)
    _require_suitability(db, customer_id=customer_id, product=product)
    _require_min_amount(product, amount)
    account = _require_account(db, customer_id=customer_id)
    fee = _fee(amount, product.fee_rate)
    cost = purchase_cost(product, amount)
    _require_balance(account, cost)

    # 校验全部通过：从这里开始写库。
    bought = _share(amount / product.nav)
    _apply_purchase(
        db, customer_id=customer_id, product=product, shares=bought, amount=amount, now=now
    )
    account.available_balance = account.available_balance - cost
    transaction = _submit(
        db,
        publisher=publisher,
        customer_id=customer_id,
        product=product,
        transaction_type=PURCHASE,
        amount=amount,
        shares=bought,
        fee=fee,
        now=now,
    )
    return _trade_result(transaction, product, account)


def redeem(
    db: Session,
    *,
    publisher: EventPublisher,
    customer_id: int,
    product_code: str,
    shares: Decimal,
    now: datetime,
) -> dict:
    """赎回：按份额赎回，金额 = 份额 × 净值 - 手续费。

    校验集与申购同一套（spec：「全部经过适当性、余额、起投金额、产品状态的校验」，
    ADR-0018 同此口径），不因为方向不同而少守一道。起投金额与可用余额只对申购成立，
    因此那两条不在这里。
    """
    if shares <= 0:
        raise AppError(400, NON_POSITIVE_SHARES_MESSAGE)
    product = _require_product(db, product_code)
    _require_suitability(db, customer_id=customer_id, product=product)
    account = _require_account(db, customer_id=customer_id)
    holding = _find_holding(db, customer_id=customer_id, product_id=product.id)
    if holding is None:
        raise AppError(400, HOLDING_MISSING_MESSAGE)
    if shares > holding.shares:
        raise AppError(400, NOT_ENOUGH_SHARES_MESSAGE)

    # 成交金额是毛额（份额 × 净值），手续费单列一行——与申购侧同一个形状，`fin_transaction.amount`
    # 因此始终是成交金额而不是到账金额；到账金额是可用余额这一步的效果。
    gross = redemption_amount(product, shares)
    fee = _fee(gross, product.fee_rate)
    proceeds = gross - fee
    if proceeds <= 0:
        raise AppError(400, NON_POSITIVE_AMOUNT_MESSAGE)

    # 校验全部通过：从这里开始写库。
    _apply_redemption(holding, shares=shares)
    account.available_balance = account.available_balance + proceeds
    transaction = _submit(
        db,
        publisher=publisher,
        customer_id=customer_id,
        product=product,
        transaction_type=REDEEM,
        amount=gross,
        shares=shares,
        fee=fee,
        now=now,
    )
    return _trade_result(transaction, product, account)


def _require_payee(payee_name: str, payee_account: str) -> tuple[str, str]:
    """收款人姓名与账号都非空：去掉首尾空白再判，写进库的也是归一化后的值。"""
    name = payee_name.strip()
    account = payee_account.strip()
    if not name:
        raise AppError(400, MISSING_PAYEE_NAME_MESSAGE)
    if not account:
        raise AppError(400, MISSING_PAYEE_ACCOUNT_MESSAGE)
    return name, account


def _transfer_no(occurred_at: datetime) -> str:
    return f"{TRANSFER_NO_PREFIX}{occurred_at:%Y%m%d%H%M%S}{uuid4().hex[:6].upper()}"


def _deposit_no(occurred_at: datetime) -> str:
    return f"{DEPOSIT_NO_PREFIX}{occurred_at:%Y%m%d%H%M%S}{uuid4().hex[:6].upper()}"


def transfer(
    db: Session,
    *,
    publisher: EventPublisher,
    customer_id: int,
    payee_name: str,
    payee_account: str,
    amount: Decimal,
    now: datetime,
) -> dict:
    """转账：校验通过后当场成交，并照常进风控。

    转账没有产品（ADR-0019），因此适当性、起投金额与产品状态三条不适用；对手方是
    机构之外的收款人，客户与收款人之间是什么关系不是受理该判断的事。校验全部在写库
    之前，被拒绝的转账在库里不留任何痕迹。

    事实落在 `fin_transfer` 里而不是 `fin_transaction`，但它与申购赎回走的是**同一个**
    交易事件入海口——风控不关心事实存在哪张表，它要的是「发生了什么」。
    """
    if amount <= 0:
        raise AppError(400, NON_POSITIVE_AMOUNT_MESSAGE)
    name, account_no = _require_payee(payee_name, payee_account)
    account = _require_account(db, customer_id=customer_id)
    _require_balance(account, amount)

    # 校验全部通过：从这里开始写库。客户自助发起，因此 operator_id 为空（Q22）。
    number = _transfer_no(now)
    row = Transfer(
        transfer_no=number,
        customer_id=customer_id,
        amount=amount,
        payee_name=name,
        payee_account=account_no,
        create_time=now,
    )
    db.add(row)
    account.available_balance = account.available_balance - amount
    # 落库由入海口提交（转账行与余额的变动此刻还在同一个会话里），于是「成交」与
    # 「钱的变动」在同一次提交中发生——与申购赎回完全一样。
    db.flush()
    alerting.submit_transaction_event(
        db,
        publisher=publisher,
        submission=alerting.TransactionSubmission(
            customer_id=customer_id,
            product_id=None,
            transaction_type=TRANSFER,
            amount=amount,
            occurred_at=now,
            transaction_id=row.id,
            transaction_no=number,
        ),
        operator_id=None,
        now=now,
    )
    return {
        "transaction": serialize_transfer(row),
        "available_balance": format(account.available_balance, "f"),
    }


def deposit(
    db: Session,
    *,
    publisher: EventPublisher,
    customer_id: int,
    amount: Decimal,
    now: datetime,
) -> dict:
    """充值：客户把机构之外的钱转入自己的资金账户，余额只增（Q7）。

    受理校验只有两条：金额为正、资金账户存在。不设限额、不要风评——大额入金交给
    规则引擎申报与预警，而不是在受理侧拒收（ADR-0018 的延续）；风评门槛只属于申购。

    事实落在 `fin_deposit` 里而不是 `fin_transaction`（ADR-0023），但它与申购赎回、
    转账走的是**同一个**交易事件入海口——风控不关心事实存在哪张表，它要的是「发生了
    什么」。余额只增：`available_balance += _money(amount)`，因此
    `CHECK available_balance >= 0` 恒成立。
    """
    if amount <= 0:
        raise AppError(400, NON_POSITIVE_AMOUNT_MESSAGE)
    account = _require_account(db, customer_id=customer_id)

    # 校验全部通过：从这里开始写库。客户自助发起，因此 operator_id 为空（Q22）。
    number = _deposit_no(now)
    row = Deposit(
        deposit_no=number,
        customer_id=customer_id,
        amount=amount,
        create_time=now,
    )
    db.add(row)
    account.available_balance = account.available_balance + _money(amount)
    # 落库由入海口提交（充值行与余额的变动此刻还在同一个会话里），于是「成交」与
    # 「钱的变动」在同一次提交中发生——与转账完全一样。
    db.flush()
    alerting.submit_transaction_event(
        db,
        publisher=publisher,
        submission=alerting.TransactionSubmission(
            customer_id=customer_id,
            product_id=None,
            transaction_type=DEPOSIT,
            amount=amount,
            occurred_at=now,
            transaction_id=row.id,
            transaction_no=number,
        ),
        operator_id=None,
        now=now,
    )
    return {
        "transaction": serialize_deposit(row),
        "available_balance": format(account.available_balance, "f"),
    }
