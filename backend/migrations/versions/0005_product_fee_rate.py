"""product disclosed fee rate

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-15

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, Sequence[str], None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "fin_product",
        sa.Column(
            "fee_rate",
            sa.Numeric(precision=7, scale=4),
            nullable=False,
            server_default="0.0000",
            comment="费率",
        ),
    )


def downgrade() -> None:
    op.drop_column("fin_product", "fee_rate")
