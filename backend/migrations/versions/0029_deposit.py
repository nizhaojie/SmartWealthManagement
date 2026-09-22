"""deposit

Revision ID: 0029
Revises: 0028
Create Date: 2026-09-22

ticket 01。充值独立成表（ADR-0023，ADR-0019 的延续）：它没有产品，因此不进
`fin_transaction`；把充值塞进 `fin_transfer` 则会让收款人两列在充值行上恒为空。
与 `fin_transfer` 同形：`deposit_no`、`customer_id`、`amount`、`create_time`，
`CHECK amount > 0`，不带 status 列——受理通过即入账（Q5），状态在客户侧合并读里
统一给「已确认」。

金额精度与 `fin_transaction.amount` 对齐为 DECIMAL(18,2)：多张表合进同一个列表，
两种口径的尾数会当场现形。`create_time` 是成交时间，由受理侧显式写入。

`amount > 0` 是「充值金额必须大于零」在表结构上的落点：受理服务负责给出可读的拒绝
理由，这一列保证即使有代码绕过服务也写不出一笔金额为零或为负的充值。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0029"
down_revision: Union[str, Sequence[str], None] = "0028"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "fin_deposit",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("deposit_no", sa.String(length=64), nullable=False, comment="充值流水号"),
        sa.Column("customer_id", sa.BigInteger(), nullable=False, comment="客户标识"),
        sa.Column(
            "amount",
            sa.Numeric(precision=18, scale=2),
            nullable=False,
            comment="充值金额",
        ),
        sa.Column("create_time", sa.DateTime(), nullable=False, comment="成交时间"),
        sa.ForeignKeyConstraint(["customer_id"], ["sys_customer.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("deposit_no"),
        sa.CheckConstraint("amount > 0", name="ck_deposit_amount_positive"),
        comment="充值",
    )
    op.create_index("ix_fin_deposit_customer_id", "fin_deposit", ["customer_id"])


def downgrade() -> None:
    # 整表一起删，不单独 drop_index：`ix_fin_deposit_customer_id` 同时是客户外键依赖的
    # 索引，先删索引会被 MySQL 拒绝（1553）。
    op.drop_table("fin_deposit")
