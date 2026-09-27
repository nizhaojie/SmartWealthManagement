"""conversation_archive.answer_data —— 归档里存一份结构化数据结果

Revision ID: 0033
Revises: 0032
Create Date: 2026-09-27

客户侧的数据回答从本轮起携带一张结果表（ADR-0028），而文本收敛为「行数 + 截断 +
口径」。客户「历史记录」读的是同一份归档（ADR-0015），若归档只留收敛后的文本，
回看里那一轮就只剩一句话——实时有表、回看无表，信息量差一个量级。

因此归档多存一份**客户看到的结构化结果**：它按客户契约的形态落库（中文表头、
无 `customer_id`、无 SQL、无 `va_*`），回看与实时是同一张表。它**不过** ``mask_pii``
的三条文本正则（那是给自然语言文本用的）：它的字段面是视图定义的封闭列集合，值就是
客户可见视图里的值，再打一次码只会让回看与实时不一致。

新开一列而不是塞进 ``content``：``content`` 是客户看到的那段话，归档举证的正是
「客户当时看到了什么」（ADR-0012），把结构化结果混进文本会让两者都失去形状。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0033"
down_revision: Union[str, Sequence[str], None] = "0032"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "conversation_archive",
        sa.Column(
            "answer_data",
            sa.JSON(),
            nullable=True,
            comment="这一轮的结构化数据结果（客户契约，ADR-0028）",
        ),
    )


def downgrade() -> None:
    op.drop_column("conversation_archive", "answer_data")
