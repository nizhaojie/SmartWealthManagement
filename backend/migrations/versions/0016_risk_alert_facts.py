"""risk alert facts: hit rules and confidence

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-16

预警要记全它作为事实记录该有的东西（ticket 02）：命中了哪些规则、置信度多少。
`fin_risk_alert` 建表时（0001 骨架）只有预警级别与一段自由文本，说不出「命中的
规则标识」，也说不出置信度——而分级展示与排序都要用。

两列都带 server default：表在真实环境里可能已有行（骨架期人工塞的演示数据），
给 NOT NULL 列加默认值才不会让迁移在这些库上失败。JSON 的默认值必须是表达式
（`JSON_ARRAY()`），MySQL 不给 JSON 列接受字符串字面量默认值。

`status` / `handler_id` / `handle_result` 三列不动：它们是预警自身的处置留痕，
归属处置链路，不在本 ticket 的范围内。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: Union[str, Sequence[str], None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "fin_risk_alert",
        sa.Column(
            "confidence",
            sa.Numeric(precision=5, scale=2),
            nullable=False,
            server_default=sa.text("0.00"),
            comment="置信度；仅用于排序与分级展示",
        ),
    )
    op.add_column(
        "fin_risk_alert",
        sa.Column(
            "rule_codes",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("(JSON_ARRAY())"),
            comment="命中的规则编号",
        ),
    )


def downgrade() -> None:
    op.drop_column("fin_risk_alert", "rule_codes")
    op.drop_column("fin_risk_alert", "confidence")
