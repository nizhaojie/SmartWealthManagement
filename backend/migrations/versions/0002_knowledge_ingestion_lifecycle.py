"""knowledge ingestion lifecycle

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-15

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, Sequence[str], None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "fin_knowledge_meta",
        sa.Column("stage", sa.String(length=16), nullable=True, comment="处理阶段"),
    )
    op.add_column(
        "fin_knowledge_meta",
        sa.Column("failure_reason", sa.Text(), nullable=True, comment="失败原因"),
    )


def downgrade() -> None:
    op.drop_column("fin_knowledge_meta", "failure_reason")
    op.drop_column("fin_knowledge_meta", "stage")
