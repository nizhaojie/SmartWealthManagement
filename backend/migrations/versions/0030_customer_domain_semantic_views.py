"""customer-domain semantic views for the customer service agent (ADR-0025)

Revision ID: 0030
Revises: 0029
Create Date: 2026-09-24

建立客户域语义视图地基，与迁移 0008 的员工侧视图**完全分开**（ADR-0025）：客户用
自然语言查自己的数据，走的是同一条分析链路，但视图另起一套。

1. ``analytics_customer_id()`` —— 读取当前连接会话变量 ``@analytics_customer_id``
   的函数，与员工侧的 ``analytics_employee_id()`` 成对但各自独立。未设置身份时函数
   返回 NULL，四张客户域视图因此返回零行（fail closed，与 0008 同手法）。
2. 四张只读语义视图（``va_my_`` = view for analytics, mine），列面以客户既有的
   REST 数据面为准（``app/api/customer_assets.py``、``customer_transactions.py``、
   ``funding_account.py``、``risk_assessment.py``）：持仓明细、交易流水（申购赎回
   + 转账 + 充值三类合并）、资金账户、风险承受等级结论。
3. **本人数据不脱敏**：客户看的是自己的数据，脱敏没有对象——列面里也本就没有
   身份证号、手机号、真实姓名、银行卡号。员工侧的脱敏与口径一行不动。

行级范围规则：只有 ``customer_id = analytics_customer_id()`` 的行。会话变量对执行
账号自身不设防，因此执行层只允许单条只读语句（``app.analytics.validation``）；
多语句在驱动层即被拒绝，护栏测试固定这一前提。

执行账号（``wealth_analytics``）对四张新视图的 SELECT 不在本迁移中——迁移账号没有
GRANT 权限，由 ``app.db.analytics_account.setup_analytics_account`` 在迁移之后
以 root 完成（与 0008 同一处）。
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0030"
down_revision: Union[str, Sequence[str], None] = "0029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 行级条件：只有凭证客户自己的行。未设置身份时函数返回 NULL，比较不成立。
_SCOPE_CONDITION = "customer_id = analytics_customer_id()"

# 交易流水的三类来源在视图里共用一个形状：转账与充值没有产品，充值也没有收款人
# （ADR-0019 / ADR-0023 的分表理由），缺的那一侧一律给 NULL——三张表合进同一列
# 时列类型由第一段决定，后两段的 NULL 因此不会改变列面。
_VIEW_DEFINITIONS: dict[str, str] = {
    # 持仓明细：口径与客户资产页一致——只含「持有中」的持仓，市值是当前市值
    # （不是 份额 × 产品净值 的推导值），无持仓时零行。
    "va_my_holdings": f"""
        CREATE VIEW va_my_holdings AS
        SELECT
            h.customer_id AS customer_id,
            p.product_code AS product_code,
            p.product_name AS product_name,
            p.product_type AS product_type,
            p.risk_level AS product_risk_level,
            h.shares AS shares,
            h.cost_amount AS cost_amount,
            h.current_value AS market_value,
            h.profit_loss AS profit_loss,
            h.profit_ratio AS profit_ratio
        FROM fin_holdings h
        JOIN fin_product p ON p.id = h.product_id
        WHERE h.{_SCOPE_CONDITION} AND h.status = '持有中'
    """,
    # 交易流水：一行一笔资金操作。申赎来自 `fin_transaction`、转账来自
    # `fin_transfer`、充值来自 `fin_deposit`，三类共用一个形状。**漏掉任何一段，
    # 那一类记录在客户眼前就是整行消失**（ADR-0019 那次正是这个失败形态），
    # `test_customer_transaction_view_merges_all_three_sources` 专门盯着它。
    # 状态列：转账与充值受理通过即入账，恒为「已确认」，与客户侧合并读同一个词。
    "va_my_transactions": f"""
        CREATE VIEW va_my_transactions AS
        SELECT
            t.customer_id AS customer_id,
            t.transaction_no AS transaction_no,
            t.transaction_type AS transaction_type,
            p.product_code AS product_code,
            p.product_name AS product_name,
            t.amount AS amount,
            t.shares AS shares,
            t.nav AS nav,
            t.fee AS fee,
            t.status AS status,
            t.create_time AS traded_at,
            NULL AS payee_name,
            NULL AS payee_account
        FROM fin_transaction t
        JOIN fin_product p ON p.id = t.product_id
        WHERE t.{_SCOPE_CONDITION}
        UNION ALL
        SELECT
            f.customer_id,
            f.transfer_no,
            '转账',
            NULL,
            NULL,
            f.amount,
            NULL,
            NULL,
            NULL,
            '已确认',
            f.create_time,
            f.payee_name,
            f.payee_account
        FROM fin_transfer f
        WHERE f.{_SCOPE_CONDITION}
        UNION ALL
        SELECT
            d.customer_id,
            d.deposit_no,
            '充值',
            NULL,
            NULL,
            d.amount,
            NULL,
            NULL,
            NULL,
            '已确认',
            d.create_time,
            NULL,
            NULL
        FROM fin_deposit d
        WHERE d.{_SCOPE_CONDITION}
    """,
    # 资金账户：一行一个客户，可用余额的口径与客户资金页一致（不是画像里的总资产）。
    "va_my_funding_account": f"""
        CREATE VIEW va_my_funding_account AS
        SELECT
            a.customer_id AS customer_id,
            a.available_balance AS available_balance
        FROM fin_funding_account a
        WHERE a.{_SCOPE_CONDITION}
    """,
    # 风险承受等级结论：只含结论列（等级 + 有效期至），不含总分与答题详情——后者
    # 是内部研判材料。一行一位客户的**当前结论**，口径与 `find_current_result`
    # 一致（同一客户按标识取最后一条），历史测评不进视图。
    "va_my_risk_assessment": f"""
        CREATE VIEW va_my_risk_assessment AS
        SELECT
            a.customer_id AS customer_id,
            a.risk_level AS risk_level,
            a.valid_until AS valid_until
        FROM fin_risk_assessment a
        WHERE a.{_SCOPE_CONDITION}
          AND a.id = (
              SELECT MAX(latest.id)
              FROM fin_risk_assessment latest
              WHERE latest.customer_id = a.customer_id
          )
    """,
}


def upgrade() -> None:
    # NO SQL 声明使函数在开启 binlog 的实例上可创建；函数体只读会话变量。
    op.execute(
        "CREATE FUNCTION analytics_customer_id() RETURNS BIGINT NO SQL"
        " RETURN @analytics_customer_id"
    )
    for definition in _VIEW_DEFINITIONS.values():
        op.execute(definition)


def downgrade() -> None:
    for view_name in reversed(list(_VIEW_DEFINITIONS)):
        op.execute(f"DROP VIEW IF EXISTS {view_name}")
    op.execute("DROP FUNCTION IF EXISTS analytics_customer_id")
