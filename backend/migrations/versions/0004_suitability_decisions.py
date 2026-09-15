"""suitability decision records

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-15

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, Sequence[str], None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NOW = sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    op.create_table(
        "fin_suitability_decision",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("customer_id", sa.BigInteger(), nullable=False, comment="客户标识"),
        sa.Column("assessment_id", sa.BigInteger(), nullable=False, comment="依据的评测"),
        sa.Column("customer_risk_level", sa.String(length=8), nullable=False, comment="判定时的风险承受等级"),
        sa.Column("allowed_product_risk_levels", sa.JSON(), nullable=False, comment="允许的产品风险等级"),
        sa.Column("decided_at", sa.DateTime(), nullable=False, comment="判定时间"),
        sa.Column("create_time", sa.DateTime(), server_default=_NOW, nullable=False),
        sa.ForeignKeyConstraint(["customer_id"], ["sys_customer.id"]),
        sa.ForeignKeyConstraint(["assessment_id"], ["fin_risk_assessment.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "customer_risk_level IN ('C1','C2','C3','C4','C5')",
            name="ck_suitability_customer_risk_level",
        ),
        comment="适当性判定记录",
    )
    op.create_index(
        "ix_suitability_decision_customer_id",
        "fin_suitability_decision",
        ["customer_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_suitability_decision_customer_id", table_name="fin_suitability_decision")
    op.drop_table("fin_suitability_decision")
