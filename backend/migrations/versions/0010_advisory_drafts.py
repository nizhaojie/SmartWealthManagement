"""advisory drafts

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-16

投顾助手 Agent 的 AI 原稿（ticket 02）：生成时落库，此后不可修改——没有
update_time，也没有任何服务代码对这张表发 UPDATE。原稿与后续顾问定稿
并存，两者的差异是举证「审核是实质性的」的依据。

同时记录生成时使用的画像版本（画像计算时间）与候选池快照，供事后复核
「这份原稿当时是基于什么信息生成的」。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: Union[str, Sequence[str], None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NOW = sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    op.create_table(
        "biz_advisory_draft",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("customer_id", sa.BigInteger(), nullable=False, comment="客户标识"),
        sa.Column("advisor_id", sa.BigInteger(), nullable=False, comment="发起生成的理财顾问"),
        sa.Column("tilt", sa.String(length=16), nullable=False, comment="生成时指定的侧重"),
        sa.Column(
            "content_classification",
            sa.String(length=32),
            nullable=False,
            comment="内容分类",
        ),
        sa.Column("candidates", sa.JSON(), nullable=False, comment="排序后的候选产品与推荐理由"),
        sa.Column("allocation_suggestion", sa.JSON(), nullable=False, comment="资产配置比例建议"),
        sa.Column("warnings", sa.JSON(), nullable=False, comment="画像警示"),
        sa.Column(
            "profile_computed_at",
            sa.DateTime(),
            nullable=False,
            comment="生成时使用的画像版本（画像计算时间）",
        ),
        sa.Column(
            "candidate_pool_snapshot", sa.JSON(), nullable=False, comment="生成时的候选池快照"
        ),
        sa.Column("generated_at", sa.DateTime(), nullable=False, comment="生成时间"),
        sa.Column("create_time", sa.DateTime(), server_default=_NOW, nullable=False),
        sa.ForeignKeyConstraint(["customer_id"], ["sys_customer.id"]),
        sa.ForeignKeyConstraint(["advisor_id"], ["sys_employee.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "content_classification IN ('投顾内容','事实性内容')",
            name="ck_advisory_draft_content_classification",
        ),
        comment="AI 原稿",
    )
    op.create_index(
        "ix_advisory_draft_customer_id",
        "biz_advisory_draft",
        ["customer_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_advisory_draft_customer_id", table_name="biz_advisory_draft")
    op.drop_table("biz_advisory_draft")
