"""product underlying holdings

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-15

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: Union[str, Sequence[str], None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NOW = sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    op.create_table(
        "fin_underlying_asset",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("asset_code", sa.String(length=32), nullable=False, comment="底层资产代码"),
        sa.Column("asset_name", sa.String(length=128), nullable=False, comment="底层资产名称"),
        sa.Column("asset_category", sa.String(length=32), nullable=False, comment="资产大类"),
        sa.Column("create_time", sa.DateTime(), server_default=_NOW, nullable=False),
        sa.Column("update_time", sa.DateTime(), server_default=_NOW, nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("asset_code"),
        sa.CheckConstraint(
            "asset_category IN ('现金','债券','股票','另类')",
            name="ck_underlying_asset_category",
        ),
        comment="底层资产",
    )
    op.create_table(
        "fin_product_underlying",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False, comment="产品标识"),
        sa.Column(
            "child_product_id",
            sa.BigInteger(),
            nullable=True,
            comment="作为底层资产的产品标识",
        ),
        sa.Column("underlying_asset_id", sa.BigInteger(), nullable=True, comment="底层资产标识"),
        sa.Column(
            "weight",
            sa.Numeric(precision=9, scale=6),
            nullable=False,
            comment="占该产品的比例",
        ),
        sa.Column("create_time", sa.DateTime(), server_default=_NOW, nullable=False),
        sa.Column("update_time", sa.DateTime(), server_default=_NOW, nullable=False),
        sa.ForeignKeyConstraint(["child_product_id"], ["fin_product.id"]),
        sa.ForeignKeyConstraint(["product_id"], ["fin_product.id"]),
        sa.ForeignKeyConstraint(["underlying_asset_id"], ["fin_underlying_asset.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "product_id", "child_product_id", name="uk_product_underlying_child"
        ),
        sa.UniqueConstraint(
            "product_id", "underlying_asset_id", name="uk_product_underlying_asset"
        ),
        sa.CheckConstraint(
            "(child_product_id IS NOT NULL AND underlying_asset_id IS NULL)"
            " OR (child_product_id IS NULL AND underlying_asset_id IS NOT NULL)",
            name="ck_product_underlying_single_target",
        ),
        sa.CheckConstraint("weight > 0", name="ck_product_underlying_weight"),
        comment="产品底层持有关系",
    )


def downgrade() -> None:
    op.drop_table("fin_product_underlying")
    op.drop_table("fin_underlying_asset")
