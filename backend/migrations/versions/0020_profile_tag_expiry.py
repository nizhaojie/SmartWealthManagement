"""profile tag expiry flag

Revision ID: 0020
Revises: 0019
Create Date: 2026-09-17

ticket 03：置信度的周期校准要把时间衰减后低于阈值的画像标签标记为**已过期**，于是
画像面板能把「这条信息该重新确认了」与「这条信息是新鲜的」区分开。

这里只落一个布尔标记，不落每个标签的置信度数值：置信度是派生值，读取时按显式传入的
时间基准重算（ADR-0011 / ADR-0012），存下来就会变成第二份真相，迟早对不上。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: Union[str, Sequence[str], None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "fin_profile_tag",
        sa.Column(
            "expired",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
            comment="是否已过期",
        ),
    )


def downgrade() -> None:
    op.drop_column("fin_profile_tag", "expired")
