"""agent_debug_trace.data_query —— 客户数据查询这一轮的查询材料

Revision ID: 0031
Revises: 0030
Create Date: 2026-09-24

客户侧的数据查询（ADR-0025）不能只留一句问答：要能事后回答「系统当时生成了什么
查询、命中了哪些语义视图、取回几行」。这些是调试材料，与提示词、检索片段同类，
因此落在**调试级留痕**上（保留期满即清），而不是新建审计表——审计级的
``conversation_archive`` 已经记下了问答本身。

新开一列而不是塞进 ``prompt`` 或 ``retrieval_snippets``：那两列的语义分别是「送进
模型的提示词」与「检索到的原始片段」，数据查询既不经过检索，也不是同一回事。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0031"
down_revision: Union[str, Sequence[str], None] = "0030"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "agent_debug_trace",
        sa.Column(
            "data_query",
            sa.JSON(),
            nullable=True,
            comment="数据查询的查询材料（生成的查询、命中的视图、行数）",
        ),
    )


def downgrade() -> None:
    op.drop_column("agent_debug_trace", "data_query")
