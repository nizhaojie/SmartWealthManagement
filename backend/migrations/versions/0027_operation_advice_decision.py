"""operation advice customer decision

Revision ID: 0027
Revises: 0026
Create Date: 2026-09-21

操作建议送达之后的客户决定（CONTEXT「客户决定」）：一条建议最多一条，记着谁、什么时候、
对哪条建议、接受还是拒绝。建议在客户侧的另外两种终态不在这里——`待客户决定` 是没有这一行，
`已过期` 从送达时间现算（`app.operation_advice.decision`）。

`advice_id` 唯一：决定只有一次，重复接受靠数据库这一条约束兜底，而不是靠应用层先读后写。
接受成功后产生的那笔交易在 `fin_transaction` 里，与这条记录由受理侧的同一次提交一起落库，
所以这里不存交易标识——「有没有交易」按方向回查，不必再存一份可能对不上的副本。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0027"
down_revision: Union[str, Sequence[str], None] = "0026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NOW = sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    op.create_table(
        "biz_operation_advice_decision",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("advice_id", sa.BigInteger(), nullable=False, comment="对应的操作建议"),
        sa.Column("customer_id", sa.BigInteger(), nullable=False, comment="做出决定的客户"),
        sa.Column("decision", sa.String(length=8), nullable=False, comment="接受或拒绝"),
        sa.Column("decided_at", sa.DateTime(), nullable=False, comment="决定时间"),
        sa.Column("create_time", sa.DateTime(), server_default=_NOW, nullable=False),
        sa.ForeignKeyConstraint(["advice_id"], ["biz_operation_advice_draft.id"]),
        sa.ForeignKeyConstraint(["customer_id"], ["sys_customer.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("advice_id", name="uk_operation_advice_decision_advice"),
        sa.CheckConstraint(
            "decision IN ('接受','拒绝')",
            name="ck_operation_advice_decision",
        ),
        comment="客户决定",
    )
    op.create_index(
        "ix_operation_advice_decision_customer_id",
        "biz_operation_advice_decision",
        ["customer_id"],
    )


def downgrade() -> None:
    # 整表一起删，不单独 drop_index：`ix_operation_advice_decision_customer_id` 同时是
    # 客户外键依赖的索引，先删索引会被 MySQL 拒绝（1553）。
    op.drop_table("biz_operation_advice_decision")
