"""va_customer_overview 的姓名列改为实名（ADR-0029）

Revision ID: 0034
Revises: 0033
Create Date: 2026-09-27

迁移 0008 把 ``customer_name`` 定义成脱敏值（保留姓、其余星号）。实测的后果不是
「查不到」，而是**答错**：员工在工作台其他每一处看到的都是明文姓名，于是问「客户王守成
的持仓情况」时带全名，生成的 ``WHERE customer_name = '王守成'`` 恒 0 行，解读再把它说成
「该客户当前无任何持仓记录，资产规模为 0」——而那位客户名下确有一笔持仓（2026-09-27 实测）。

本迁移按 ADR-0029 把这一列换成实名，其余列、行级条件与 ``analytics_employee_id()`` /
``analytics_employee_role()`` 两个函数一字不动：身份证号、手机号、银行卡号、密码散列
仍然结构性不进视图，变的只有姓名——它是员工在客户列表里本来就看得见的信息。

用 ``CREATE OR REPLACE VIEW`` 而不是 DROP + CREATE：受限执行账号
``wealth_analytics`` 对这张视图的 SELECT 授权跟着视图对象走，重建一次就得靠
``setup_analytics_account`` 再补一遍授权——中间那一段是「视图在、账号没权限」。
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0034"
down_revision: Union[str, Sequence[str], None] = "0033"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_VIEW_NAME = "va_customer_overview"

# 0008 的脱敏表达式，downgrade 用它把口径退回去（冻结的字面量，不 import 应用代码）。
_MASKED_NAME = (
    "CONCAT(LEFT(c.real_name, 1), REPEAT('*', CHAR_LENGTH(c.real_name) - 1))"
)

# 行级过滤条件与 0008 逐字相同：全量范围角色，或名下客户；未设置身份时两侧均为 NULL。
# COLLATE 固定在比较处：函数返回值跟随建库 collation，而字面量跟随连接 collation，
# 两者不同会让 IN 报「Illegal mix of collations」。
_SCOPE_CONDITION = (
    "analytics_employee_role() COLLATE utf8mb4_unicode_ci IN ('理财顾问', '风控专员')"
    " OR c.manager_id = analytics_employee_id()"
)


def _definition(name_expression: str) -> str:
    return f"""
        CREATE OR REPLACE VIEW {_VIEW_NAME} AS
        SELECT
            c.id AS customer_id,
            {name_expression} AS customer_name,
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
    """


def upgrade() -> None:
    op.execute(_definition("c.real_name"))


def downgrade() -> None:
    op.execute(_definition(_MASKED_NAME))
