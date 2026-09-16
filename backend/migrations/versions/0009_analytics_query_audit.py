"""analytics query audit trail

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-16

数据分析 Agent 的审计级留痕（ticket 02）：每次查询留下永久记录——
提问人、问题、生成的查询、返回行数。被拒绝或失败的尝试同样留痕
（status + error_code），让「谁试图越权取数」事后可追溯。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: Union[str, Sequence[str], None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NOW = sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    op.create_table(
        "biz_analytics_query_audit",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("employee_id", sa.BigInteger(), nullable=False, comment="提问人"),
        sa.Column("question", sa.Text(), nullable=False, comment="自然语言问题"),
        sa.Column("generated_sql", sa.Text(), nullable=True, comment="生成的查询"),
        sa.Column("status", sa.String(length=16), nullable=False, comment="结果状态"),
        sa.Column("row_count", sa.Integer(), nullable=True, comment="返回行数"),
        sa.Column(
            "truncated",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
            comment="是否被截断",
        ),
        sa.Column("error_code", sa.Integer(), nullable=True, comment="业务错误码"),
        sa.Column("create_time", sa.DateTime(), server_default=_NOW, nullable=False),
        sa.ForeignKeyConstraint(["employee_id"], ["sys_employee.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "status IN ('成功','超出可查范围','生成失败','校验拒绝','查询超时','执行失败')",
            name="ck_analytics_query_audit_status",
        ),
        comment="数据分析查询留痕",
    )
    op.create_index(
        "ix_analytics_query_audit_employee_id",
        "biz_analytics_query_audit",
        ["employee_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_analytics_query_audit_employee_id",
        table_name="biz_analytics_query_audit",
    )
    op.drop_table("biz_analytics_query_audit")
