"""risk focus

Revision ID: 0021
Revises: 0020
Create Date: 2026-09-17

ticket 04：Agent 之间通过事件总线协作，订阅方收到广播后各自留下一条**风险关注**
记录。它不是预警（预警是规则命中的事实记录）也不是工单（处置流程的载体），而是
「谁在什么时候因为什么提醒了谁」的留痕，投顾据此在方案上加风险标记，风控据此
看到客服察觉到的高风险意图。

不落原始事件载荷：广播不是数据通道，记录只留读取方要看的那几样（谁、什么、何时、
什么等级），需要完整追溯时回到权威来源（见 `app.risk_focus`）。

`customer_id` 建索引：两个读取方向都是「这位客户有哪些关注」。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: Union[str, Sequence[str], None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NOW = sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    op.create_table(
        "biz_risk_focus",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("customer_id", sa.BigInteger(), nullable=False, comment="客户标识"),
        sa.Column("focus_type", sa.String(length=32), nullable=False, comment="关注类型"),
        sa.Column("severity", sa.String(length=8), nullable=True, comment="等级；无等级时为空"),
        sa.Column("reason", sa.Text(), nullable=False, comment="关注理由"),
        sa.Column("source", sa.String(length=32), nullable=False, comment="事件来源 Agent"),
        sa.Column("trace_id", sa.String(length=64), nullable=True, comment="追踪标识"),
        sa.Column("occurred_at", sa.DateTime(), nullable=False, comment="事件发生时间"),
        sa.Column("create_time", sa.DateTime(), server_default=_NOW, nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["customer_id"], ["sys_customer.id"]),
        comment="风险关注",
    )
    op.create_index("ix_risk_focus_customer_id", "biz_risk_focus", ["customer_id"])


def downgrade() -> None:
    # 不单独 drop_index：外键要求 customer_id 上有索引，MySQL 会拒绝删掉它正在用的
    # 那个（1553 needed in a foreign key constraint），整表删掉则索引与外键一并走。
    op.drop_table("biz_risk_focus")
