"""advisory review and final

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-16

审核流（ticket 03）：`biz_advisory_review` 记录一份 AI 原稿的审核状态与
并发锁，`thread_id` 指向生成流程在 LangGraph 运行时上的线程——放行或
驳回时靠它把那次运行从中断处恢复，状态持久化交给运行时的检查点，这张
表只落审核这一侧的状态。`biz_advisory_review_audit` 记录每次审核操作的
审核人、时间与理由。`biz_advisory_final` 是顾问定稿，落库后不可修改，
与原稿并存供差异核对，也是唯一允许经客户侧接口读取的版本。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: Union[str, Sequence[str], None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NOW = sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    op.create_table(
        "biz_advisory_review",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("draft_id", sa.BigInteger(), nullable=False, comment="对应的 AI 原稿"),
        sa.Column(
            "thread_id",
            sa.String(length=64),
            nullable=False,
            comment="生成流程在运行时上的线程标识",
        ),
        sa.Column("status", sa.String(length=16), nullable=False, comment="审核状态"),
        sa.Column("create_time", sa.DateTime(), server_default=_NOW, nullable=False),
        sa.Column(
            "update_time",
            sa.DateTime(),
            server_default=_NOW,
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["draft_id"], ["biz_advisory_draft.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("draft_id"),
        sa.UniqueConstraint("thread_id"),
        sa.CheckConstraint(
            "status IN ('待审','处理中','已放行','已驳回')",
            name="ck_advisory_review_status",
        ),
        comment="投顾内容审核状态",
    )

    op.create_table(
        "biz_advisory_review_audit",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("review_id", sa.BigInteger(), nullable=False, comment="对应的审核记录"),
        sa.Column("advisor_id", sa.BigInteger(), nullable=False, comment="审核人"),
        sa.Column("action", sa.String(length=8), nullable=False, comment="操作"),
        sa.Column("reason", sa.Text(), nullable=True, comment="驳回理由"),
        sa.Column("decided_at", sa.DateTime(), nullable=False, comment="操作时间"),
        sa.Column("create_time", sa.DateTime(), server_default=_NOW, nullable=False),
        sa.ForeignKeyConstraint(["review_id"], ["biz_advisory_review.id"]),
        sa.ForeignKeyConstraint(["advisor_id"], ["sys_employee.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "action IN ('放行','驳回')",
            name="ck_advisory_review_audit_action",
        ),
        comment="审核操作留痕",
    )
    op.create_index(
        "ix_advisory_review_audit_review_id",
        "biz_advisory_review_audit",
        ["review_id"],
        unique=False,
    )

    op.create_table(
        "biz_advisory_final",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("draft_id", sa.BigInteger(), nullable=False, comment="对应的 AI 原稿"),
        sa.Column("customer_id", sa.BigInteger(), nullable=False, comment="客户标识"),
        sa.Column("advisor_id", sa.BigInteger(), nullable=False, comment="放行的理财顾问"),
        sa.Column(
            "content_classification",
            sa.String(length=32),
            nullable=False,
            comment="内容分类",
        ),
        sa.Column(
            "candidates", sa.JSON(), nullable=False, comment="顾问确认后的推荐产品与理由"
        ),
        sa.Column(
            "allocation_suggestion", sa.JSON(), nullable=False, comment="顾问确认后的配置建议"
        ),
        sa.Column("warnings", sa.JSON(), nullable=False, comment="顾问确认后的画像警示"),
        sa.Column("released_at", sa.DateTime(), nullable=False, comment="放行时间"),
        sa.Column("create_time", sa.DateTime(), server_default=_NOW, nullable=False),
        sa.ForeignKeyConstraint(["draft_id"], ["biz_advisory_draft.id"]),
        sa.ForeignKeyConstraint(["customer_id"], ["sys_customer.id"]),
        sa.ForeignKeyConstraint(["advisor_id"], ["sys_employee.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("draft_id"),
        sa.CheckConstraint(
            "content_classification IN ('投顾内容','事实性内容')",
            name="ck_advisory_final_content_classification",
        ),
        comment="顾问定稿",
    )
    op.create_index(
        "ix_advisory_final_customer_id",
        "biz_advisory_final",
        ["customer_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_advisory_final_customer_id", table_name="biz_advisory_final")
    op.drop_table("biz_advisory_final")
    op.drop_index(
        "ix_advisory_review_audit_review_id", table_name="biz_advisory_review_audit"
    )
    op.drop_table("biz_advisory_review_audit")
    op.drop_table("biz_advisory_review")
