"""risk rules

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-16

20 条反洗钱可疑交易识别规则存在库里而不是硬编码（ticket 01）。

`operator`、`field` 与 `window_hours` 都带 CHECK 约束，清单与
`app.risk_monitoring.operators` / `app.risk_monitoring.fields` 里的注册表一致：
想加一种判定方式必须改代码并出迁移，规则数据自己不能变出新的形状。

`fin_risk_rule_change` 记阈值与启停的每次变更。阈值是监管口径的落点，「现在的
阈值」说不清它是初始口径还是被谁调过，所以变更本身要留痕。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: Union[str, Sequence[str], None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NOW = sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    op.create_table(
        "fin_risk_rule",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("rule_code", sa.String(length=16), nullable=False, comment="规则编号"),
        sa.Column("rule_name", sa.String(length=128), nullable=False, comment="规则名称"),
        sa.Column("category", sa.String(length=32), nullable=False, comment="规则分类"),
        sa.Column("description", sa.Text(), nullable=False, comment="触发条件描述"),
        sa.Column("field", sa.String(length=32), nullable=False, comment="被判定的字段"),
        sa.Column("operator", sa.String(length=32), nullable=False, comment="运算符"),
        sa.Column("threshold", sa.JSON(), nullable=False, comment="阈值"),
        sa.Column(
            "window_hours",
            sa.Integer(),
            nullable=True,
            comment="时间窗长度（小时），仅时间窗算子使用",
        ),
        sa.Column("alert_level", sa.String(length=8), nullable=False, comment="预警等级"),
        sa.Column("weight", sa.Numeric(precision=5, scale=2), nullable=False, comment="规则权重"),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("1"),
            comment="是否启用；停用后不参与匹配",
        ),
        sa.Column("create_time", sa.DateTime(), server_default=_NOW, nullable=False),
        sa.Column("update_time", sa.DateTime(), server_default=_NOW, nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("rule_code", name="uk_risk_rule_code"),
        sa.CheckConstraint(
            "alert_level IN ('轻度','中度','重度')",
            name="ck_risk_rule_alert_level",
        ),
        sa.CheckConstraint(
            "operator IN ("
            "'gt','gte','lt','lte','eq','ne','between','outside',"
            "'window_count_gte','window_sum_gte','window_max_gte',"
            "'window_distinct_count_gte','daily_count_gte','daily_sum_gte')",
            name="ck_risk_rule_operator",
        ),
        sa.CheckConstraint(
            "window_hours IS NOT NULL OR operator NOT IN "
            "('window_count_gte','window_sum_gte','window_max_gte',"
            "'window_distinct_count_gte')",
            name="ck_risk_rule_window_hours",
        ),
        sa.CheckConstraint(
            "field IN ("
            "'amount','purchase_amount','redeem_amount','hour_of_day',"
            "'amount_to_assets_ratio','risk_level_gap','reverse_interval_hours',"
            "'threshold_avoidance_amount','small_amount','large_round_amount',"
            "'product_id')",
            name="ck_risk_rule_field",
        ),
        comment="风控规则",
    )
    op.create_table(
        "fin_risk_rule_change",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("rule_id", sa.BigInteger(), nullable=False, comment="规则标识"),
        sa.Column("change_type", sa.String(length=16), nullable=False, comment="调整类型"),
        sa.Column("old_value", sa.JSON(), nullable=False, comment="调整前的配置项"),
        sa.Column("new_value", sa.JSON(), nullable=False, comment="调整后的配置项"),
        sa.Column("changed_by", sa.BigInteger(), nullable=False, comment="调整人"),
        sa.Column("reason", sa.Text(), nullable=False, comment="调整理由"),
        sa.Column("changed_at", sa.DateTime(), nullable=False, comment="调整时间"),
        sa.Column("create_time", sa.DateTime(), server_default=_NOW, nullable=False),
        sa.ForeignKeyConstraint(["rule_id"], ["fin_risk_rule.id"]),
        sa.ForeignKeyConstraint(["changed_by"], ["sys_employee.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "change_type IN ('阈值调整','启停变更')",
            name="ck_risk_rule_change_type",
        ),
        comment="风控规则调整记录",
    )
    op.create_index("ix_risk_rule_change_rule_id", "fin_risk_rule_change", ["rule_id"])


def downgrade() -> None:
    # 先删子表：它的外键要求 rule_id 上有索引，单独 drop_index 会被 MySQL 拒绝
    #（1553 needed in a foreign key constraint），整表删掉则索引与外键一并走。
    op.drop_table("fin_risk_rule_change")
    op.drop_table("fin_risk_rule")
