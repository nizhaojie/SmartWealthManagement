"""generalize review content type

Revision ID: 0026
Revises: 0025
Create Date: 2026-09-21

ADR-0020。审核记录表就地泛化：`content_type` 标注这条审核审的是哪一类投顾内容，
`content_ref` 指向该类内容的载荷记录（方案指向 `biz_advisory_draft.id`，操作建议
指向 `biz_operation_advice_draft.id`）。表名继续带着「方案」字样是刻意的不一致——
改它要连同数据迁移与两个前端一起动，收益只是命名好看。

既有行回填为「方案」且 `content_ref = draft_id`：它们本来就是方案的审核记录。
`draft_id` 随之改为可空——它成了方案特有的列，操作建议不跟着它走。回填用的
`server_default` 在回填之后撤掉，否则新插入会悄悄变成「方案」。

`(content_type, content_ref)` 唯一：同一份内容最多一条审核记录，这条约束对两类
内容一视同仁，也是「加锁加在审核记录上」的前提。

`biz_operation_advice_draft` 是操作建议的载荷——另一个内容类型的载荷另建表
（ADR-0020），不让方案特有的候选池快照、配置建议以一堆空列的形式跟着建议走。
它没有 `update_time`：AI 原稿落库后不可修改，与 `biz_advisory_draft` 同一条约束。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0026"
down_revision: Union[str, Sequence[str], None] = "0025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NOW = sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    op.add_column(
        "biz_advisory_review",
        sa.Column(
            "content_type",
            sa.String(length=32),
            nullable=False,
            server_default="方案",
            comment="内容类型",
        ),
    )
    op.add_column(
        "biz_advisory_review",
        sa.Column(
            "content_ref",
            sa.BigInteger(),
            nullable=True,
            comment="内容引用（该类型载荷记录的主键）",
        ),
    )
    op.execute("UPDATE biz_advisory_review SET content_ref = draft_id")
    op.alter_column(
        "biz_advisory_review", "content_ref", existing_type=sa.BigInteger(), nullable=False
    )
    op.alter_column(
        "biz_advisory_review",
        "content_type",
        existing_type=sa.String(length=32),
        nullable=False,
        server_default=None,
    )
    op.alter_column(
        "biz_advisory_review", "draft_id", existing_type=sa.BigInteger(), nullable=True
    )
    op.create_check_constraint(
        "ck_advisory_review_content_type",
        "biz_advisory_review",
        "content_type IN ('方案','操作建议')",
    )
    op.create_index(
        "uq_advisory_review_content",
        "biz_advisory_review",
        ["content_type", "content_ref"],
        unique=True,
    )

    op.create_table(
        "biz_operation_advice_draft",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("customer_id", sa.BigInteger(), nullable=False, comment="客户标识"),
        sa.Column(
            "manager_id",
            sa.BigInteger(),
            nullable=False,
            comment="发起这条建议的客户经理",
        ),
        sa.Column("product_code", sa.String(length=32), nullable=False, comment="建议的产品代码"),
        sa.Column("direction", sa.String(length=8), nullable=False, comment="操作方向"),
        sa.Column(
            "amount",
            sa.Numeric(precision=18, scale=2),
            nullable=False,
            comment="建议金额",
        ),
        sa.Column("reason", sa.Text(), nullable=False, comment="建议理由"),
        sa.Column(
            "content_classification",
            sa.String(length=32),
            nullable=False,
            comment="内容分类",
        ),
        sa.Column("generated_at", sa.DateTime(), nullable=False, comment="生成时间"),
        sa.Column("create_time", sa.DateTime(), server_default=_NOW, nullable=False),
        sa.ForeignKeyConstraint(["customer_id"], ["sys_customer.id"]),
        sa.ForeignKeyConstraint(["manager_id"], ["sys_employee.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "direction IN ('申购','赎回')",
            name="ck_operation_advice_draft_direction",
        ),
        sa.CheckConstraint(
            "amount > 0",
            name="ck_operation_advice_draft_amount_positive",
        ),
        sa.CheckConstraint(
            "content_classification IN ('投顾内容','事实性内容')",
            name="ck_operation_advice_draft_content_classification",
        ),
        comment="操作建议原稿",
    )
    op.create_index(
        "ix_operation_advice_draft_customer_id",
        "biz_operation_advice_draft",
        ["customer_id"],
    )


def downgrade() -> None:
    # 操作建议这一类内容在旧结构里无处安放（没有 content_type，draft_id 又非空），
    # 降级只能把它们连同审核留痕与留言一起删掉，否则恢复 draft_id 非空时会被 NULL 挡住。
    op.execute(
        "DELETE c FROM biz_advisory_review_comment c "
        "JOIN biz_advisory_review r ON r.id = c.review_id WHERE r.content_type <> '方案'"
    )
    op.execute(
        "DELETE a FROM biz_advisory_review_audit a "
        "JOIN biz_advisory_review r ON r.id = a.review_id WHERE r.content_type <> '方案'"
    )
    op.execute("DELETE FROM biz_advisory_review WHERE content_type <> '方案'")

    # 整表一起删，不单独 drop_index：`ix_operation_advice_draft_customer_id` 同时是
    # 客户外键依赖的索引，先删索引会被 MySQL 拒绝（1553）。
    op.drop_table("biz_operation_advice_draft")
    op.drop_index("uq_advisory_review_content", table_name="biz_advisory_review")
    op.drop_constraint(
        "ck_advisory_review_content_type", "biz_advisory_review", type_="check"
    )
    op.alter_column(
        "biz_advisory_review", "draft_id", existing_type=sa.BigInteger(), nullable=False
    )
    op.drop_column("biz_advisory_review", "content_ref")
    op.drop_column("biz_advisory_review", "content_type")
