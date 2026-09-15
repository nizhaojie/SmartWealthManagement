"""profile tags and conflict records

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-15

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, Sequence[str], None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NOW = sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    op.create_table(
        "fin_profile_tag",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("customer_id", sa.BigInteger(), nullable=False, comment="客户标识"),
        sa.Column("tag_key", sa.String(length=32), nullable=False, comment="标签键"),
        sa.Column("tag_value", sa.JSON(), nullable=False, comment="标签值"),
        sa.Column("source", sa.String(length=32), nullable=False, comment="来源"),
        sa.Column("evidence_count", sa.Integer(), nullable=False, comment="证据条数"),
        sa.Column("observed_at", sa.DateTime(), nullable=False, comment="写入时间"),
        sa.Column("reason", sa.Text(), nullable=True, comment="修正理由"),
        sa.Column("create_time", sa.DateTime(), server_default=_NOW, nullable=False),
        sa.Column("update_time", sa.DateTime(), server_default=_NOW, nullable=False),
        sa.ForeignKeyConstraint(["customer_id"], ["sys_customer.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("customer_id", "tag_key", name="uk_profile_tag_customer_key"),
        comment="客户画像标签",
    )
    op.create_table(
        "fin_profile_tag_conflict",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("customer_id", sa.BigInteger(), nullable=False, comment="客户标识"),
        sa.Column("tag_key", sa.String(length=32), nullable=False, comment="标签键"),
        sa.Column("old_value", sa.JSON(), nullable=False, comment="旧值"),
        sa.Column("old_source", sa.String(length=32), nullable=False, comment="旧来源"),
        sa.Column("new_value", sa.JSON(), nullable=False, comment="新值"),
        sa.Column("new_source", sa.String(length=32), nullable=False, comment="新来源"),
        sa.Column("changed_at", sa.DateTime(), nullable=False, comment="覆盖时间"),
        sa.Column("reason", sa.Text(), nullable=True, comment="修正理由"),
        sa.Column("create_time", sa.DateTime(), server_default=_NOW, nullable=False),
        sa.ForeignKeyConstraint(["customer_id"], ["sys_customer.id"]),
        sa.PrimaryKeyConstraint("id"),
        comment="客户画像标签冲突记录",
    )
    op.create_index(
        "ix_profile_tag_conflict_customer_key",
        "fin_profile_tag_conflict",
        ["customer_id", "tag_key"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_profile_tag_conflict_customer_key", table_name="fin_profile_tag_conflict")
    op.drop_table("fin_profile_tag_conflict")
    op.drop_table("fin_profile_tag")
