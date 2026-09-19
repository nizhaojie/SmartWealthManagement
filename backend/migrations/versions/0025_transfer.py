"""transfer

Revision ID: 0025
Revises: 0024
Create Date: 2026-09-19

ticket 03。转账独立成表（ADR-0019）：它没有产品，因此不进 `fin_transaction`——把交易
流水表的产品外键改成可空，会让资产页、语义视图、持仓穿透以及所有按产品读流水的地方
都开始处理空值，而它们拿一笔没有产品的流水几乎无事可做。客户侧的「交易流水」把两张
表合并读出一张列表。

金额精度与 `fin_transaction.amount` 对齐为 DECIMAL(18,2)：两张表合进同一个列表，
两种口径的尾数会当场现形。`create_time` 是成交时间，与交易流水一样由受理侧显式写入
（成交发生在客户按下确认的那一刻，不是落库那一刻）。

`amount > 0` 是「转账金额必须大于零」在表结构上的落点：受理服务负责给出可读的拒绝
理由，这一列保证即使有代码绕过服务也写不出一笔金额为零或为负的转账。收款人姓名与
账号的非空由受理侧把关——那是业务口径，不是数据完整性口径。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0025"
down_revision: Union[str, Sequence[str], None] = "0024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "fin_transfer",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("transfer_no", sa.String(length=64), nullable=False, comment="转账流水号"),
        sa.Column("customer_id", sa.BigInteger(), nullable=False, comment="客户标识"),
        sa.Column(
            "amount",
            sa.Numeric(precision=18, scale=2),
            nullable=False,
            comment="转账金额",
        ),
        sa.Column("payee_name", sa.String(length=128), nullable=False, comment="收款人姓名"),
        sa.Column("payee_account", sa.String(length=64), nullable=False, comment="收款人账号"),
        sa.Column("create_time", sa.DateTime(), nullable=False, comment="成交时间"),
        sa.ForeignKeyConstraint(["customer_id"], ["sys_customer.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("transfer_no"),
        sa.CheckConstraint("amount > 0", name="ck_transfer_amount_positive"),
        comment="转账",
    )
    op.create_index("ix_fin_transfer_customer_id", "fin_transfer", ["customer_id"])


def downgrade() -> None:
    # 整表一起删，不单独 drop_index：`ix_fin_transfer_customer_id` 同时是客户外键依赖的
    # 索引，先删索引会被 MySQL 拒绝（1553）。
    op.drop_table("fin_transfer")
