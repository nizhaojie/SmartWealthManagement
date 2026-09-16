"""semantic views for the data analysis agent (ADR-0010)

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-16

建立数据分析 Agent 的语义视图地基：

1. ``sys_customer.manager_id`` —— 客户关系归属人（客户经理），行级权限的事实来源。
2. ``analytics_employee_id()`` / ``analytics_employee_role()`` —— 读取当前连接
   会话变量的函数。MySQL 视图不能直接引用用户变量，经函数中转后，
   行级过滤条件得以内建在视图定义里。未设置身份时函数返回 NULL，
   所有带行级权限的视图返回零行（fail closed）。
3. 五个只读语义视图（``va_`` = view for analytics），覆盖客户概况、持仓分布、
   交易统计、产品要素、预警统计。敏感字段（身份证号、手机号、银行卡号、
   密码散列）一律不进视图；真实姓名只以脱敏形式（姓 + 星号）出现。

行级范围规则：理财顾问与风控专员为全量范围；客户经理只能看到名下客户
（``sys_customer.manager_id`` = 当前员工）的行。

已知边界：会话变量对执行账号自身不设防——如果模型生成的语句能携带
``SET @analytics_employee_role = ...``，行级过滤会被自我提权。因此执行层
（ticket 02）必须只允许单条只读语句；多语句在驱动层（PyMySQL 默认不开
MULTI_STATEMENTS）即被拒绝，并有护栏测试固定这一前提。

执行账号（``wealth_analytics``）的创建与授权不在本迁移中——迁移账号没有
CREATE USER / GRANT 权限，由 ``app.db.analytics_account.setup_analytics_account``
在本迁移执行之后以 root 完成。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: Union[str, Sequence[str], None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 行级过滤条件：全量范围角色，或名下客户。未设置身份时两侧均为 NULL，不成立。
# COLLATE 固定在比较处：函数返回值跟随建库 collation，而字面量跟随连接
# collation，两者不同会让 IN 报「Illegal mix of collations」。
_SCOPE_CONDITION = (
    "analytics_employee_role() COLLATE utf8mb4_unicode_ci IN ('理财顾问', '风控专员')"
    " OR c.manager_id = analytics_employee_id()"
)

# 真实姓名脱敏：保留姓，其余以星号替代。
_MASKED_NAME = "CONCAT(LEFT(c.real_name, 1), REPEAT('*', CHAR_LENGTH(c.real_name) - 1))"

_VIEW_DEFINITIONS: dict[str, str] = {
    # 客户概况：一行一个客户。资产规模口径固定为「持有中」持仓的当前市值合计，
    # 无持仓为 0，不由调用方临时拼聚合。
    "va_customer_overview": f"""
        CREATE VIEW va_customer_overview AS
        SELECT
            c.id AS customer_id,
            {_MASKED_NAME} AS customer_name,
            c.customer_level AS customer_level,
            p.risk_level AS customer_risk_level,
            COALESCE(SUM(CASE WHEN h.status = '持有中' THEN h.current_value END), 0)
                AS asset_scale,
            COUNT(DISTINCT CASE WHEN h.status = '持有中' THEN h.product_id END)
                AS holding_count,
            c.opened_at AS opened_at
        FROM sys_customer c
        LEFT JOIN fin_customer_profile p ON p.customer_id = c.id
        LEFT JOIN fin_holdings h ON h.customer_id = c.id
        WHERE {_SCOPE_CONDITION}
        GROUP BY c.id, c.real_name, c.customer_level, p.risk_level, c.opened_at
    """,
    # 持仓分布：一行一条持仓，带上产品要素，供按产品类型 / 风险等级聚合。
    "va_holding_distribution": f"""
        CREATE VIEW va_holding_distribution AS
        SELECT
            h.customer_id AS customer_id,
            p.product_code AS product_code,
            p.product_name AS product_name,
            p.product_type AS product_type,
            p.risk_level AS product_risk_level,
            h.shares AS shares,
            h.cost_amount AS cost_amount,
            h.current_value AS current_value,
            h.profit_loss AS profit_loss,
            h.profit_ratio AS profit_ratio,
            h.status AS holding_status
        FROM fin_holdings h
        JOIN fin_product p ON p.id = h.product_id
        JOIN sys_customer c ON c.id = h.customer_id
        WHERE {_SCOPE_CONDITION}
    """,
    # 交易统计：一行一笔交易，带上产品要素，供按时间 / 类型 / 产品聚合。
    "va_transaction_stat": f"""
        CREATE VIEW va_transaction_stat AS
        SELECT
            t.transaction_no AS transaction_no,
            t.customer_id AS customer_id,
            p.product_code AS product_code,
            p.product_name AS product_name,
            p.product_type AS product_type,
            t.transaction_type AS transaction_type,
            t.amount AS amount,
            t.shares AS shares,
            t.nav AS nav,
            t.fee AS fee,
            t.status AS transaction_status,
            t.create_time AS trade_time
        FROM fin_transaction t
        JOIN fin_product p ON p.id = t.product_id
        JOIN sys_customer c ON c.id = t.customer_id
        WHERE {_SCOPE_CONDITION}
    """,
    # 产品要素：产品主数据，不含客户数据，因此无行级过滤。
    "va_product_element": """
        CREATE VIEW va_product_element AS
        SELECT
            product_code,
            product_name,
            product_type,
            risk_level,
            expected_return,
            min_amount,
            term_days,
            fee_rate,
            fund_manager,
            status AS product_status
        FROM fin_product
    """,
    # 预警统计：一行一条预警。触发详情与处置结论是自由文本，可能夹带
    # 任何内容，不进视图。
    "va_risk_alert_stat": f"""
        CREATE VIEW va_risk_alert_stat AS
        SELECT
            a.id AS alert_id,
            a.customer_id AS customer_id,
            a.alert_type AS alert_type,
            a.alert_level AS alert_level,
            a.status AS alert_status,
            a.create_time AS alerted_at
        FROM fin_risk_alert a
        JOIN sys_customer c ON c.id = a.customer_id
        WHERE {_SCOPE_CONDITION}
    """,
}


def upgrade() -> None:
    op.add_column(
        "sys_customer",
        sa.Column(
            "manager_id",
            sa.BigInteger(),
            nullable=True,
            comment="客户关系归属人（客户经理）",
        ),
    )
    op.create_index(
        "ix_sys_customer_manager_id", "sys_customer", ["manager_id"], unique=False
    )
    op.create_foreign_key(
        "fk_sys_customer_manager",
        "sys_customer",
        "sys_employee",
        ["manager_id"],
        ["id"],
    )

    # NO SQL 声明使函数在开启 binlog 的实例上可创建；函数体只读会话变量。
    op.execute(
        "CREATE FUNCTION analytics_employee_id() RETURNS BIGINT NO SQL"
        " RETURN @analytics_employee_id"
    )
    op.execute(
        "CREATE FUNCTION analytics_employee_role()"
        " RETURNS VARCHAR(32) CHARSET utf8mb4 COLLATE utf8mb4_unicode_ci NO SQL"
        " RETURN @analytics_employee_role"
    )

    for definition in _VIEW_DEFINITIONS.values():
        op.execute(definition)


def downgrade() -> None:
    for view_name in reversed(list(_VIEW_DEFINITIONS)):
        op.execute(f"DROP VIEW IF EXISTS {view_name}")
    op.execute("DROP FUNCTION IF EXISTS analytics_employee_role")
    op.execute("DROP FUNCTION IF EXISTS analytics_employee_id")
    op.drop_constraint("fk_sys_customer_manager", "sys_customer", type_="foreignkey")
    op.drop_index("ix_sys_customer_manager_id", table_name="sys_customer")
    op.drop_column("sys_customer", "manager_id")
