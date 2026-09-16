"""work order lifecycle: source alert, handle result and transition log

Revision ID: 0017
Revises: 0016
Create Date: 2026-09-16

工单（ticket 03）在建表时（0001 骨架）只有一组通用列，说不出两件事：

- 它是从哪条预警派生出来的。`source_alert_id` 补上这一列，并带唯一约束——
  **一条预警最多派生一张工单**。预警之外的来源（客户投诉、转人工）留空，而
  MySQL 的唯一索引允许多个 NULL，所以这类工单可以有很多张。
- 处置结论是什么。`handle_result` 与 `handle_reason`（最近一次流转理由）分开：
  前者是结论，后者是这一次流转为什么发生。

`biz_work_order_transition` 是只追加的流转留痕：每次流转的处置人、时间与理由。
只靠工单行上的「最近一次理由」看不出「它一路是怎么走到今天的」，而处置过程要可
审计，所以每次流转都写一条——建单也写一条（`from_status` 为空），工单的第一个
状态同样有出处。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: Union[str, Sequence[str], None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NOW = sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    op.add_column(
        "biz_work_order",
        sa.Column(
            "source_alert_id",
            sa.BigInteger(),
            nullable=True,
            comment="来源预警标识；一条预警最多派生一张工单",
        ),
    )
    op.add_column(
        "biz_work_order",
        sa.Column("handle_result", sa.Text(), nullable=True, comment="处置结论"),
    )
    op.create_foreign_key(
        "fk_work_order_source_alert",
        "biz_work_order",
        "fin_risk_alert",
        ["source_alert_id"],
        ["id"],
    )
    op.create_unique_constraint(
        "uk_work_order_source_alert", "biz_work_order", ["source_alert_id"]
    )

    op.create_table(
        "biz_work_order_transition",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("work_order_id", sa.BigInteger(), nullable=False, comment="对应的工单"),
        sa.Column(
            "from_status", sa.String(length=16), nullable=True, comment="流转前状态；建单时为空"
        ),
        sa.Column("to_status", sa.String(length=16), nullable=False, comment="流转后状态"),
        sa.Column("handler_id", sa.BigInteger(), nullable=False, comment="处置人"),
        # 非空是「每次流转必须是填了理由的」在库里的落点：理由为空的请求在服务层被
        # 拒绝，绕过服务层也写不进这一列。
        sa.Column("reason", sa.Text(), nullable=False, comment="流转理由"),
        sa.Column("handled_at", sa.DateTime(), nullable=False, comment="处置时间"),
        sa.Column("create_time", sa.DateTime(), server_default=_NOW, nullable=False),
        sa.ForeignKeyConstraint(["work_order_id"], ["biz_work_order.id"]),
        sa.ForeignKeyConstraint(["handler_id"], ["sys_employee.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "to_status IN ('待处理','处理中','已完成','已关闭')",
            name="ck_work_order_transition_to_status",
        ),
        comment="工单状态流转留痕",
    )
    op.create_index(
        "ix_work_order_transition_work_order_id",
        "biz_work_order_transition",
        ["work_order_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_work_order_transition_work_order_id", table_name="biz_work_order_transition"
    )
    op.drop_table("biz_work_order_transition")
    op.drop_constraint("uk_work_order_source_alert", "biz_work_order", type_="unique")
    op.drop_constraint("fk_work_order_source_alert", "biz_work_order", type_="foreignkey")
    op.drop_column("biz_work_order", "handle_result")
    op.drop_column("biz_work_order", "source_alert_id")
