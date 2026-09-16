"""underlying asset industry

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-16

行业集中度（ticket 05）需要一个比 `asset_category`（现金/债券/股票/另类，
四个大类）更细的维度——大类本身就是目标/实际配置对比图已经在展示的东西，
拿它当集中度信号没有新增信息。这里给底层资产加一个独立的 `industry` 字段，
两者互不覆盖：大类回答「这笔钱是什么资产」，行业回答「挤在哪个行业里」。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: Union[str, Sequence[str], None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "fin_underlying_asset",
        sa.Column(
            "industry",
            sa.String(length=32),
            nullable=False,
            server_default="未分类",
            comment="所属行业",
        ),
    )


def downgrade() -> None:
    op.drop_column("fin_underlying_asset", "industry")
