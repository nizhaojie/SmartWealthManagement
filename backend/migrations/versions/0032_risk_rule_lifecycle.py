"""risk rule lifecycle: soft delete, category check and five change types

Revision ID: 0032
Revises: 0031
Create Date: 2026-09-24

规则可以被创建、修改与删除，于是三件事必须一起落到库里（ADR-0026 / ADR-0027）。

`deleted_at` 非空即已删除。删除是**软删**：`fin_risk_rule_change` 有指向
`fin_risk_rule.id` 的外键，硬删要么级联丢掉整张留痕表，要么报错，而那张表存在的全部
理由是「阈值是监管口径的落点，说不清它是初始口径还是被谁调过」（`0015`）。行因此留在
库里：列表默认过滤，变更记录与历史预警快照都还指得到它。

`category` 此前是唯一没有约束的列。ADR-0026 把「可写」的边界定在注册表内，专员在表单
上选的就是这一列，它的清单必须与 `app.risk_monitoring.rules` 里的 7 个分类常量是同一
份——`field` 与 `operator` 在 `0015` 已经这么立过规矩，这里补上第三列。

`fin_risk_rule_change.change_type` 从 2 个值扩为 5 个：规则可新建、可修改、可删除，
三种新动作与既有的阈值调整、启停变更一样各记一条留痕，读者看到的五种类型是同一层
语义，不该有两个来源不一致的清单。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0032"
down_revision: Union[str, Sequence[str], None] = "0031"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "fin_risk_rule",
        sa.Column(
            "deleted_at",
            sa.DateTime(),
            nullable=True,
            comment="删除时间；为空表示仍在用",
        ),
    )
    op.create_index("ix_risk_rule_deleted_at", "fin_risk_rule", ["deleted_at"])
    op.create_check_constraint(
        "ck_risk_rule_category",
        "fin_risk_rule",
        "category IN ("
        "'大额交易','频繁交易','快进快出','拆分规避','异常时段','资产错配','适当性')",
    )
    op.drop_constraint("ck_risk_rule_change_type", "fin_risk_rule_change", type_="check")
    op.create_check_constraint(
        "ck_risk_rule_change_type",
        "fin_risk_rule_change",
        "change_type IN ('规则新建','规则修改','规则删除','阈值调整','启停变更')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_risk_rule_change_type", "fin_risk_rule_change", type_="check")
    op.create_check_constraint(
        "ck_risk_rule_change_type",
        "fin_risk_rule_change",
        "change_type IN ('阈值调整','启停变更')",
    )
    op.drop_constraint("ck_risk_rule_category", "fin_risk_rule", type_="check")
    # 索引先删再删列：MySQL 会随列一起丢掉索引，但那时候名字已经不在手里了。
    op.drop_index("ix_risk_rule_deleted_at", table_name="fin_risk_rule")
    op.drop_column("fin_risk_rule", "deleted_at")
