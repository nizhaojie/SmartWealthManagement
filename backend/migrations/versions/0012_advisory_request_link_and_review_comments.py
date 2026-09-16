"""advisory request link and review comments

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-16

审核队列（ticket 04）需要把客户提交的方案请求（`biz_advisory_request`）接住：
`biz_advisory_draft.advisory_request_id` 记录一份原稿是不是由某条客户请求触发
生成的（顾问自行发起生成时为空），放行/驳回时据此把请求状态带着走。

`biz_advisory_review_comment` 是审核页上顾问与客户经理之间的留言，不是审核
决定本身——放行/驳回仍然只走 `biz_advisory_review_audit`，这张表纯粹是沟通
留痕，删掉也不影响审核记录的完整性。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: Union[str, Sequence[str], None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NOW = sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    op.add_column(
        "biz_advisory_draft",
        sa.Column(
            "advisory_request_id",
            sa.BigInteger(),
            nullable=True,
            comment="触发本次生成的客户方案请求（顾问自行发起时为空）",
        ),
    )
    op.create_foreign_key(
        "fk_advisory_draft_advisory_request_id",
        "biz_advisory_draft",
        "biz_advisory_request",
        ["advisory_request_id"],
        ["id"],
    )

    op.create_table(
        "biz_advisory_review_comment",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("review_id", sa.BigInteger(), nullable=False, comment="对应的审核记录"),
        sa.Column("author_id", sa.BigInteger(), nullable=False, comment="留言人"),
        sa.Column("author_role", sa.String(length=32), nullable=False, comment="留言人角色"),
        sa.Column("body", sa.Text(), nullable=False, comment="留言内容"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="留言时间"),
        sa.Column("create_time", sa.DateTime(), server_default=_NOW, nullable=False),
        sa.ForeignKeyConstraint(["review_id"], ["biz_advisory_review.id"]),
        sa.ForeignKeyConstraint(["author_id"], ["sys_employee.id"]),
        sa.PrimaryKeyConstraint("id"),
        comment="审核留言",
    )
    op.create_index(
        "ix_advisory_review_comment_review_id",
        "biz_advisory_review_comment",
        ["review_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_advisory_review_comment_review_id", table_name="biz_advisory_review_comment"
    )
    op.drop_table("biz_advisory_review_comment")
    op.drop_constraint(
        "fk_advisory_draft_advisory_request_id", "biz_advisory_draft", type_="foreignkey"
    )
    op.drop_column("biz_advisory_draft", "advisory_request_id")
