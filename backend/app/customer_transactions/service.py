"""客户可见视图中的交易流水：申购、赎回、转账与充值合并成一张列表。

客户标识一律由调用方从身份推导后传入，本模块不接受任何来自请求体的客户标识。
"""

from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select

from app.customer_assets.service import _format_amount
from app.db.models import Deposit, Product, Transaction, Transfer
from app.pagination import PageParams, paginate

TRANSFER = "转账"
DEPOSIT = "充值"
# 转账与充值都是既成事实：受理通过的那一刻它们就已经完成，没有「待确认」这种中间态。
# 取值与 `app.risk_monitoring.alerting.TRANSACTION_STATUS_CONFIRMED` 一致——几张表合进
# 同一个列表之后，状态列在客户眼里应当是同一个词。
CONFIRMED_STATUS = "已确认"

# 合并读的排序兜底：成交时间相同时用它把几张表分成确定的先后（见 `list_transactions`）。
# 这是一处 N 表扇入：加第四类记录时，在这里给它一个来源序号、写一个同形的 `_xxx_rows`
# 并把它挂进 `list_transactions` 的类型分支。漏掉哪一张表，那一类记录在客户眼前就是
# 整行消失——不报错（ADR-0019 那次正是这个失败形态）。
_FLOW_TRANSACTION = 0
_FLOW_TRANSFER = 1
_FLOW_DEPOSIT = 2


def _format_optional(value: Decimal | None) -> str | None:
    """没有这一项时给空而不是给零：转账没有份额，写 `0.0000` 是在陈述一个不存在的事实。"""
    return None if value is None else _format_amount(value)


def _serialize_flow(
    *,
    transaction_no: str,
    transaction_type: str,
    amount: Decimal,
    shares: Decimal | None,
    nav: Decimal | None,
    fee: Decimal | None,
    status: str,
    traded_at: datetime,
    product: Product | None = None,
    transfer: Transfer | None = None,
) -> dict:
    """两类流水共用的呈现形状：键只有这一份。

    客户在「流水」里看到的与刚成交时看到的是同一笔记录，形状因此只有一份：各拼一遍
    的话，加字段时总有一个视图会漏掉它，而漏掉的那个视图看起来仍然「正常」。

    `product` 与 `transfer` 是两类记录各自的专属信息（ADR-0019）：申赎有产品、没有
    收款人，转账有收款人、没有产品。传进来的那一个之外，其余专属列一律为空——合并读
    的两类记录因此共用一个形状，界面不必按类型分叉。
    """
    return {
        "transaction_no": transaction_no,
        "transaction_type": transaction_type,
        "product_code": product.product_code if product is not None else None,
        "product_name": product.product_name if product is not None else None,
        "amount": _format_amount(amount),
        "shares": _format_optional(shares),
        "nav": _format_optional(nav),
        "fee": _format_optional(fee),
        "status": status,
        "traded_at": traded_at.isoformat(),
        "payee_name": transfer.payee_name if transfer is not None else None,
        "payee_account": transfer.payee_account if transfer is not None else None,
    }


def serialize_transaction(transaction: Transaction, product: Product) -> dict:
    """一笔申购或赎回的呈现形状。"""
    return _serialize_flow(
        transaction_no=transaction.transaction_no,
        transaction_type=transaction.transaction_type,
        amount=transaction.amount,
        shares=transaction.shares,
        nav=transaction.nav,
        fee=transaction.fee,
        status=transaction.status,
        traded_at=transaction.create_time,
        product=product,
    )


def serialize_transfer(transfer: Transfer) -> dict:
    """一笔转账的呈现形状：没有产品，有收款人。

    `transaction_no` 用转账自己的流水号——两类记录合进一张列表之后，客户核对账目时
    每一行都有编号可对。
    """
    return _serialize_flow(
        transaction_no=transfer.transfer_no,
        transaction_type=TRANSFER,
        amount=transfer.amount,
        shares=None,
        nav=None,
        fee=None,
        status=CONFIRMED_STATUS,
        traded_at=transfer.create_time,
        transfer=transfer,
    )


def serialize_deposit(deposit: Deposit) -> dict:
    """一笔充值的呈现形状：没有产品，也没有收款人。

    `transaction_no` 用充值自己的流水号——多类记录合进一张列表之后，客户核对账目时
    每一行都有编号可对。
    """
    return _serialize_flow(
        transaction_no=deposit.deposit_no,
        transaction_type=DEPOSIT,
        amount=deposit.amount,
        shares=None,
        nav=None,
        fee=None,
        status=CONFIRMED_STATUS,
        traded_at=deposit.create_time,
    )


def _apply_time_range(
    stmt: Select,
    *,
    create_time_column,
    start_date: date | None,
    end_date: date | None,
) -> Select:
    """时间范围筛选。几张流水表各有自己的成交时间列，判定口径只有这一份。"""
    if start_date is not None:
        stmt = stmt.where(create_time_column >= datetime.combine(start_date, time.min))
    if end_date is not None:
        stmt = stmt.where(
            create_time_column < datetime.combine(end_date + timedelta(days=1), time.min)
        )
    return stmt


def _transaction_rows(
    db: Session,
    *,
    customer_id: int,
    start_date: date | None,
    end_date: date | None,
    transaction_type: str | None,
) -> list[tuple[datetime, int, int, dict]]:
    """申购与赎回：`fin_transaction` 里的行。

    `INNER JOIN fin_product` 在这里是对的——这张表的产品外键非空，每一行都有产品。
    """
    stmt = (
        select(Transaction, Product)
        .join(Product, Product.id == Transaction.product_id)
        .where(Transaction.customer_id == customer_id)
    )
    stmt = _apply_time_range(
        stmt,
        create_time_column=Transaction.create_time,
        start_date=start_date,
        end_date=end_date,
    )
    if transaction_type:
        stmt = stmt.where(Transaction.transaction_type == transaction_type)
    return [
        (
            transaction.create_time,
            _FLOW_TRANSACTION,
            transaction.id,
            serialize_transaction(transaction, product),
        )
        for transaction, product in db.execute(stmt).all()
    ]


def _transfer_rows(
    db: Session,
    *,
    customer_id: int,
    start_date: date | None,
    end_date: date | None,
) -> list[tuple[datetime, int, int, dict]]:
    """转账：`fin_transfer` 里的行，没有产品（ADR-0019）。"""
    stmt = select(Transfer).where(Transfer.customer_id == customer_id)
    stmt = _apply_time_range(
        stmt,
        create_time_column=Transfer.create_time,
        start_date=start_date,
        end_date=end_date,
    )
    return [
        (transfer.create_time, _FLOW_TRANSFER, transfer.id, serialize_transfer(transfer))
        for transfer in db.scalars(stmt).all()
    ]


def _deposit_rows(
    db: Session,
    *,
    customer_id: int,
    start_date: date | None,
    end_date: date | None,
) -> list[tuple[datetime, int, int, dict]]:
    """充值：`fin_deposit` 里的行，没有产品，也没有收款人（ADR-0023）。"""
    stmt = select(Deposit).where(Deposit.customer_id == customer_id)
    stmt = _apply_time_range(
        stmt,
        create_time_column=Deposit.create_time,
        start_date=start_date,
        end_date=end_date,
    )
    return [
        (deposit.create_time, _FLOW_DEPOSIT, deposit.id, serialize_deposit(deposit))
        for deposit in db.scalars(stmt).all()
    ]


def list_transactions(
    db: Session,
    *,
    customer_id: int,
    params: PageParams,
    start_date: date | None = None,
    end_date: date | None = None,
    transaction_type: str | None = None,
) -> dict:
    """客户名下的资金操作，按成交时间倒序，只返回 `params` 指定的那一页。

    申赎在 `fin_transaction`、转账在 `fin_transfer`、充值在 `fin_deposit`，一张列表
    因此要把三边都读上：ADR-0019 说明了分表的理由，ADR-0023 把它延续到充值，代价
    正是这里——漏掉哪一边，客户核对账目时就会少看一笔，而且不会报错。三边的序列化
    共用一个形状（见 `_serialize_flow`）。

    切片在**排序之后**：`total` 是过滤后的总条数（与页码无关），本页是那一次排序的
    一段。反过来先切后排，等于让顺序取决于三张表各自的返回顺序——翻页时同一秒的
    记录会跳到另一页去（见下面那段排序兜底）。
    """
    records: list[tuple[datetime, int, int, dict]] = []
    # 类型筛选决定要读哪几张表：筛「转账」时申赎那张表根本不用查，筛「充值」时
    # 其余两张也不必查，反之亦然。这是一处 N 表扇入——加第四类记录时照着这个分支
    # 写，漏掉一张表就是那一类记录整行消失。
    if transaction_type != TRANSFER and transaction_type != DEPOSIT:
        records.extend(
            _transaction_rows(
                db,
                customer_id=customer_id,
                start_date=start_date,
                end_date=end_date,
                transaction_type=transaction_type,
            )
        )
    if not transaction_type or transaction_type == TRANSFER:
        records.extend(
            _transfer_rows(
                db, customer_id=customer_id, start_date=start_date, end_date=end_date
            )
        )
    if not transaction_type or transaction_type == DEPOSIT:
        records.extend(
            _deposit_rows(
                db, customer_id=customer_id, start_date=start_date, end_date=end_date
            )
        )

    # 成交时间是秒精度，同一秒里的两笔本来就没有客观先后（真实系统会给成交序号，
    # 这里没有）。用「表 + 行标识」兜底把它定成确定的一种顺序，免得同一个列表两次
    # 读出来不一样——几张表的 id 各自从 1 开始，只比 id 会串。分页之后这条兜底
    # 不只是「两次读出来一样」：同一秒的记录会跨页，键不稳就等于翻页时凭空少一笔。
    records.sort(key=lambda row: (row[0], row[1], row[2]), reverse=True)
    return paginate(
        [record for _occurred_at, _kind, _id, record in records], params=params
    )
