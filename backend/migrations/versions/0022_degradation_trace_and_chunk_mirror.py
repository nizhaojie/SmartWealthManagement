"""degradation trace and knowledge chunk mirror

Revision ID: 0022
Revises: 0021
Create Date: 2026-09-17

ticket 05。两张表服务同一条要求——「外部依赖抖动时给降级后的服务，而不是把错误
抛给使用者」：

- `biz_degradation_trace`：每次降级写一行。降级不是错误（使用者仍拿到一次正常响应），
  所以它不该只活在日志文件里，否则「系统有多少时间在降级状态下工作」无法统计。
- `fin_knowledge_chunk`：分块正文的 MySQL 镜像。Milvus 超时或不可用时，关键词
  检索依赖它；检索正常时它不参与任何计算。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: Union[str, Sequence[str], None] = "0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NOW = sa.text("CURRENT_TIMESTAMP")
_MEDIUMTEXT = sa.dialects.mysql.MEDIUMTEXT()


def upgrade() -> None:
    op.create_table(
        "biz_degradation_trace",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("dependency", sa.String(length=32), nullable=False, comment="被降级的外部依赖"),
        sa.Column("reason", sa.String(length=64), nullable=False, comment="降级原因"),
        sa.Column("agent_type", sa.String(length=32), nullable=True, comment="触发降级的 Agent"),
        sa.Column("trace_id", sa.String(length=64), nullable=True, comment="贯穿全链路的追踪标识"),
        sa.Column("detail", sa.Text(), nullable=True, comment="补充说明"),
        sa.Column("create_time", sa.DateTime(), server_default=_NOW, nullable=False),
        sa.PrimaryKeyConstraint("id"),
        comment="降级留痕",
    )
    op.create_index("ix_degradation_trace_trace_id", "biz_degradation_trace", ["trace_id"])
    op.create_index("ix_degradation_trace_dependency", "biz_degradation_trace", ["dependency"])
    op.create_index("ix_degradation_trace_create_time", "biz_degradation_trace", ["create_time"])

    op.create_table(
        "fin_knowledge_chunk",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("knowledge_id", sa.BigInteger(), nullable=False, comment="所属知识文档"),
        sa.Column("knowledge_type", sa.String(length=32), nullable=False, comment="知识类型"),
        sa.Column("chunk_index", sa.Integer(), nullable=False, comment="分块序号"),
        sa.Column("heading_path", sa.JSON(), nullable=False, comment="标题路径"),
        sa.Column("content", _MEDIUMTEXT, nullable=False, comment="分块正文"),
        sa.Column("create_time", sa.DateTime(), server_default=_NOW, nullable=False),
        sa.ForeignKeyConstraint(["knowledge_id"], ["fin_knowledge_meta.id"]),
        sa.PrimaryKeyConstraint("id"),
        comment="知识分块（关键词检索兜底）",
    )
    op.create_index("ix_knowledge_chunk_knowledge_id", "fin_knowledge_chunk", ["knowledge_id"])


def downgrade() -> None:
    op.drop_index("ix_knowledge_chunk_knowledge_id", table_name="fin_knowledge_chunk")
    op.drop_table("fin_knowledge_chunk")
    op.drop_index("ix_degradation_trace_create_time", table_name="biz_degradation_trace")
    op.drop_index("ix_degradation_trace_dependency", table_name="biz_degradation_trace")
    op.drop_index("ix_degradation_trace_trace_id", table_name="biz_degradation_trace")
    op.drop_table("biz_degradation_trace")
