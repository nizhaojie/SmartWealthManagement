"""graph sync run

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-16

知识图谱全量重建（ticket 01）的留痕与并发互斥表。`lock_key` 进行中时固定
取值，结束后置空——同一时刻只能有一条记录持有这个值，靠 UNIQUE 约束做
互斥，不引入额外的分布式锁（MySQL 唯一约束里多个 NULL 互不冲突）。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: Union[str, Sequence[str], None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NOW = sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    op.create_table(
        "biz_graph_sync_run",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "lock_key",
            sa.String(length=16),
            nullable=True,
            comment="进行中时固定取值用于并发互斥，结束后置空",
        ),
        sa.Column("status", sa.String(length=16), nullable=False, comment="重建状态"),
        sa.Column("node_count", sa.Integer(), nullable=True, comment="节点数"),
        sa.Column("relationship_count", sa.Integer(), nullable=True, comment="关系数"),
        sa.Column("started_at", sa.DateTime(), nullable=False, comment="触发时间"),
        sa.Column("duration_ms", sa.Integer(), nullable=True, comment="耗时（毫秒）"),
        sa.Column("failure_reason", sa.Text(), nullable=True, comment="失败原因"),
        sa.Column("create_time", sa.DateTime(), server_default=_NOW, nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("lock_key", name="uk_graph_sync_run_lock"),
        sa.CheckConstraint(
            "status IN ('进行中','成功','失败')",
            name="ck_graph_sync_run_status",
        ),
        comment="知识图谱全量重建记录",
    )


def downgrade() -> None:
    op.drop_table("biz_graph_sync_run")
