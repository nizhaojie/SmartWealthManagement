"""funding account

Revision ID: 0023
Revises: 0022
Create Date: 2026-09-19

ticket 01。客户第一次有了「能在这里动用的钱」的载体：一个客户一个资金账户、一个
可用余额（CONTEXT「资金账户」「可用余额」）。

余额与画像的 `total_assets` 不共用字段、不互相写：前者是机构内可动用的钱，后者是
客户自述的资产规模，把两者放在一起会让「总资产 80 万」被读成「能买 80 万」。精度
与 `fin_transaction.amount` 对齐为 DECIMAL(18,2)，否则一次赎回之后余额会带出交易
流水里不存在的尾数。

`available_balance >= 0` 是「余额不足的操作被拒绝」在表结构上的落点：受理服务负责给出
可读的拒绝理由，这一列保证即使有代码绕过服务也写不出透支。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: Union[str, Sequence[str], None] = "0022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NOW = sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    op.create_table(
        "fin_funding_account",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("customer_id", sa.BigInteger(), nullable=False, comment="客户标识"),
        sa.Column(
            "available_balance",
            sa.Numeric(precision=18, scale=2),
            nullable=False,
            comment="可用余额",
        ),
        sa.Column("create_time", sa.DateTime(), server_default=_NOW, nullable=False),
        sa.Column("update_time", sa.DateTime(), server_default=_NOW, nullable=False),
        sa.ForeignKeyConstraint(["customer_id"], ["sys_customer.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("customer_id", name="uk_funding_account_customer"),
        sa.CheckConstraint(
            "available_balance >= 0",
            name="ck_funding_account_available_balance_non_negative",
        ),
        comment="资金账户",
    )


def downgrade() -> None:
    op.drop_table("fin_funding_account")
