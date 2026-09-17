"""agent debug trace

Revision ID: 0019
Revises: 0018
Create Date: 2026-09-17

调试级留痕（ticket 02）：完整提示词、原始检索片段、token 与耗时明细。它与
`conversation_archive`（审计级：使用者、Agent、问题、最终答案、引用文档、内容分类）
是**两张表**：审计级永久保存，调试级保留期满后删除。分表让清理不可能误伤审计级，
这一点由表结构保证，而不是靠清理语句里 WHERE 条件的措辞。

`create_time` 建索引，因为清理就是按它扫「保留期之前的那批」。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: Union[str, Sequence[str], None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NOW = sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    op.create_table(
        "agent_debug_trace",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "trace_id", sa.String(length=64), nullable=False, comment="贯穿全链路的追踪标识"
        ),
        sa.Column("session_id", sa.String(length=64), nullable=True, comment="会话标识"),
        sa.Column("user_id", sa.BigInteger(), nullable=True, comment="使用者标识"),
        sa.Column("agent_type", sa.String(length=32), nullable=False, comment="Agent"),
        sa.Column("prompt", sa.JSON(), nullable=True, comment="完整提示词（按角色分条）"),
        sa.Column("retrieval_snippets", sa.JSON(), nullable=True, comment="原始检索片段"),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True, comment="输入 token 数"),
        sa.Column("completion_tokens", sa.Integer(), nullable=True, comment="输出 token 数"),
        sa.Column("duration_ms", sa.Integer(), nullable=True, comment="耗时（毫秒）"),
        sa.Column("create_time", sa.DateTime(), server_default=_NOW, nullable=False),
        sa.PrimaryKeyConstraint("id"),
        comment="调试级留痕",
    )
    op.create_index(
        "ix_agent_debug_trace_trace_id", "agent_debug_trace", ["trace_id"]
    )
    op.create_index(
        "ix_agent_debug_trace_session_id", "agent_debug_trace", ["session_id"]
    )
    op.create_index(
        "ix_agent_debug_trace_create_time", "agent_debug_trace", ["create_time"]
    )


def downgrade() -> None:
    op.drop_index("ix_agent_debug_trace_create_time", table_name="agent_debug_trace")
    op.drop_index("ix_agent_debug_trace_session_id", table_name="agent_debug_trace")
    op.drop_index("ix_agent_debug_trace_trace_id", table_name="agent_debug_trace")
    op.drop_table("agent_debug_trace")
