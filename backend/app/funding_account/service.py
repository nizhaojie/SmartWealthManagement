"""资金账户与可用余额。

一个客户一个资金账户，可用余额只装客户在本机构能在这里动用的钱。它与画像里的
`total_assets` 不共用字段、不互相写（CONTEXT「资金账户」「可用余额」）：总资产是客户
在所有地方的资产规模（自述、用于画像研判），把两者放到一起，「总资产 80 万」就会被
读成「能买 80 万」。

本模块只提供**读取**：扣减与增加发生在客户侧的受理服务里（申购与转账扣减、赎回增加），
因为可用余额的变更必须与交易落库在同一次受理中完成，读取路径不该碰它。客户标识一律由
调用方从身份推导后传入，本模块不接受任何来自请求体的客户标识。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.customer_scope import is_under_management, restrict_to_own_customers
from app.db.models import Customer, Employee, FundingAccount
from app.exceptions import AppError

ACCOUNT_MISSING_MESSAGE = "资金账户不存在"
CUSTOMER_NOT_FOUND_MESSAGE = "客户不存在"
NOT_YOUR_CUSTOMER_MESSAGE = "该客户不在你的名下，无权查看"


def get_available_balance(db: Session, *, customer_id: int) -> dict:
    account = db.scalar(
        select(FundingAccount).where(FundingAccount.customer_id == customer_id)
    )
    if account is None:
        raise AppError(404, ACCOUNT_MISSING_MESSAGE)
    # 与 `fin_transaction.amount` 同为两位小数，呈现口径也保持一致。
    return {"available_balance": format(account.available_balance, "f")}


def ensure_can_view(db: Session, employee: Employee, customer_id: int) -> None:
    """客户经理只能看自己名下客户的余额，其他内部角色不受限（`app.customer_scope`）。

    判定本身只有一份（`customer_scope`），这里只决定「看不到」对外说成什么。
    """
    if not restrict_to_own_customers(employee):
        return
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise AppError(404, CUSTOMER_NOT_FOUND_MESSAGE)
    if not is_under_management(customer, employee):
        raise AppError(403, NOT_YOUR_CUSTOMER_MESSAGE)
