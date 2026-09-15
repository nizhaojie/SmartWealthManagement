"""advisory requests

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-15

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, Sequence[str], None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NOW = sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    op.create_table(
        "biz_advisory_request",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("request_no", sa.String(length=32), nullable=False, comment="请求编号"),
        sa.Column("customer_id", sa.BigInteger(), nullable=False, comment="客户标识"),
        sa.Column("status", sa.String(length=16), nullable=False, comment="请求状态"),
        sa.Column("filters", sa.JSON(), nullable=False, comment="触发它的筛选条件"),
        sa.Column(
            "condition_fingerprint",
            sa.String(length=64),
            nullable=False,
            comment="筛选条件指纹",
        ),
        sa.Column("submitted_at", sa.DateTime(), nullable=False, comment="提交时间"),
        sa.Column("create_time", sa.DateTime(), server_default=_NOW, nullable=False),
        sa.Column("update_time", sa.DateTime(), server_default=_NOW, nullable=False),
        sa.ForeignKeyConstraint(["customer_id"], ["sys_customer.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_no"),
        sa.CheckConstraint(
            "status IN ('待处理','处理中','已完成','已关闭')",
            name="ck_advisory_request_status",
        ),
        comment="方案请求",
    )
    op.create_index(
        "ix_advisory_request_customer_fingerprint",
        "biz_advisory_request",
        ["customer_id", "condition_fingerprint"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_advisory_request_customer_fingerprint", table_name="biz_advisory_request"
    )
    op.drop_table("biz_advisory_request")
