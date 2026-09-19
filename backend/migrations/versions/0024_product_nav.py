"""product current unit nav

Revision ID: 0024
Revises: 0023
Create Date: 2026-09-19

ticket 02。产品需要一个成交价：申购 `份额 = 金额 / 净值`、赎回 `金额 = 份额 × 净值 - 手续费`。
`fin_product` 因此增加**当前单位净值**，精度与 `fin_transaction.nav` 对齐为 DECIMAL(12,6)。

只有这一个当前值，没有净值时间序列——`fin_holdings.current_value`（当前市值）因此仍然是
独立维护的字段，不改成 `份额 × 净值` 的推导值：那样等于顺手重写资产页与穿透的所有数字。

净值先按 1.000000 回填既有行，`seed` 随后写入各自的价格；`nav > 0` 的 CHECK 约束保证
受理服务里不会出现除零。默认值是回填用的，建完列就摘掉——一个没填价格的产品不该被
悄悄按 1.000000 成交。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0024"
down_revision: Union[str, Sequence[str], None] = "0023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "fin_product",
        sa.Column(
            "nav",
            sa.Numeric(precision=12, scale=6),
            nullable=False,
            server_default="1.000000",
            comment="当前单位净值",
        ),
    )
    op.alter_column(
        "fin_product",
        "nav",
        existing_type=sa.Numeric(precision=12, scale=6),
        existing_nullable=False,
        server_default=None,
    )
    op.create_check_constraint("ck_product_nav_positive", "fin_product", "nav > 0")


def downgrade() -> None:
    op.drop_constraint("ck_product_nav_positive", "fin_product", type_="check")
    op.drop_column("fin_product", "nav")
