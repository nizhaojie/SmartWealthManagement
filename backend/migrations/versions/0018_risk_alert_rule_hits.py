"""risk alert rule hits: structured evidence snapshot

Revision ID: 0018
Revises: 0017
Create Date: 2026-09-17

预警要把命中依据留成结构化数据（ticket 04）：`rule_codes` 只说得清命中了哪几条
规则，`trigger_detail` 只是一段给人读的文本。而界面要展示到字段与值的粒度——
「金额 520000 ≥ 阈值 500000」——风控专员靠这个判断误报。

阈值是可以被调整的（ticket 01：调整有记录），所以依据必须**在命中那一刻固化**，
不能等到展示时回查规则：回查会把上周的口径套在今天已经产生的预警上。这一列就是
那份快照，形状与 `RuleHit` 一一对应。

与 0016 加的 `rule_codes` 同样带 server default：骨架期可能已有预警行，给 NOT NULL
列加默认值才不会让迁移在这些库上失败；JSON 的默认值必须是表达式（`JSON_ARRAY()`）。
已有的预警在这一列上是空数组——它们的依据仍然留在 `trigger_detail` 文本里。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: Union[str, Sequence[str], None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "fin_risk_alert",
        sa.Column(
            "rule_hits",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("(JSON_ARRAY())"),
            comment="命中规则的依据快照：字段、实测值、阈值",
        ),
    )


def downgrade() -> None:
    op.drop_column("fin_risk_alert", "rule_hits")
