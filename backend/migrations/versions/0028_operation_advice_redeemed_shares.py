"""operation advice redeemed shares

Revision ID: 0028
Revises: 0027
Create Date: 2026-09-21

ADR-0021：赎回建议带上一个具体份额数。`redeemed_shares` 与 `amount` 在赎回方向是
同一件事的两种表达（份额 × 净值 = 金额），之所以存份额，是因为「赎回多少」从此在
生成时定下来；净值只有一个当前值，金额因此是可推导的——它仍然存着，那是顾问审核时
要看的那个数。

**这一列可空是既有语义，不是特例**：改动之前的赎回建议只存金额，成交的是接受那一刻
的全部持仓份额——那些行这一列为空，表示「全部赎回」。新写入的赎回建议一律带份额，
申购方向恒为空。约束因此只钉「非空就要大于零」：把「可空」读成「可选的全部赎回」、
给新行也写空值的话，「按当下的全部持仓成交」那条旧语义会被重新激活，而演示里看不出来。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0028"
down_revision: Union[str, Sequence[str], None] = "0027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "biz_operation_advice_draft",
        sa.Column(
            "redeemed_shares",
            sa.Numeric(precision=18, scale=4),
            nullable=True,
            comment="赎回份额（为空表示改动之前的全部赎回）",
        ),
    )
    op.create_check_constraint(
        "ck_operation_advice_draft_redeemed_shares_positive",
        "biz_operation_advice_draft",
        "redeemed_shares IS NULL OR redeemed_shares > 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_operation_advice_draft_redeemed_shares_positive",
        "biz_operation_advice_draft",
        type_="check",
    )
    op.drop_column("biz_operation_advice_draft", "redeemed_shares")
