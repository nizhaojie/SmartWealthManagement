"""数据分析 Agent 的受限执行账号与语义视图清单（ADR-0010 的地基）。

安全性由结构保证：
- 语义视图由迁移脚本创建（见 migrations/versions/0008），本模块的
  ``ANALYTICS_VIEW_NAMES`` 是授权清单，有测试保证它与迁移创建的视图集合一致；
- 执行账号 ``wealth_analytics`` 只对这组视图有 SELECT 权限，对基础表无任何权限；
- 行级权限内建在视图定义中：视图通过 ``analytics_employee_id()`` /
  ``analytics_employee_role()`` 两个函数读取当前连接上的会话变量，
  执行查询前必须用 ``apply_analytics_identity`` 在同一连接上设置当前员工身份。
  未设置身份时视图返回零行（fail closed）。
"""

import re

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, make_url

from app.auth.roles import ADVISOR, RISK_OFFICER
from app.settings import get_settings

_IDENTIFIER = re.compile(r"[A-Za-z0-9_]+")

ANALYTICS_VIEW_NAMES: tuple[str, ...] = (
    "va_customer_overview",
    "va_holding_distribution",
    "va_transaction_stat",
    "va_product_element",
    "va_risk_alert_stat",
)

# 拥有全量行级范围的角色；客户经理不在其中，只能看到名下客户。
# 视图定义里是同样的字面量，此处用于执行层判断与测试对照。
FULL_SCOPE_ROLES: tuple[str, ...] = (ADVISOR, RISK_OFFICER)


def analytics_url_for(base_url: str, user: str, password: str) -> str:
    """把任意数据库连接的账号换成执行账号，库名与其余参数保持不变。"""
    return make_url(base_url).set(username=user, password=password).render_as_string(
        hide_password=False
    )


def apply_analytics_identity(
    connection: Connection, *, employee_id: int, role: str
) -> None:
    """在连接上设置当前员工身份，视图的行级过滤随即以该身份生效。

    会话变量跟随连接，因此必须在执行查询的同一连接上设置；
    连接归还连接池前必须用 ``reset_analytics_identity`` 清理，
    否则下一个借用该连接的请求会继承上一个人的行级范围。
    """
    connection.execute(
        text("SET @analytics_employee_id = :employee_id"), {"employee_id": employee_id}
    )
    connection.execute(text("SET @analytics_employee_role = :role"), {"role": role})


def reset_analytics_identity(connection: Connection) -> None:
    """清空连接上的员工身份，回到 fail-closed 状态（视图返回零行）。"""
    connection.execute(text("SET @analytics_employee_id = NULL"))
    connection.execute(text("SET @analytics_employee_role = NULL"))


def setup_analytics_account(target_url: str) -> None:
    """创建受限执行账号并授权：只对语义视图有 SELECT，对基础表无任何权限。

    需要 root 连接（迁移账号没有 CREATE USER / GRANT 权限）。
    幂等：可重复执行，密码与授权会被对齐到当前配置。
    必须在迁移之后执行——GRANT 要求视图已存在。
    """
    settings = get_settings()
    user = settings.analytics_db_user
    password = settings.analytics_db_password
    database = make_url(target_url).database
    if not database:
        raise ValueError("target_url 必须包含库名")
    # 标识符无法参数化，只能拼接；拼之前限制为词字符，堵住配置注入。
    for identifier in (user, database):
        if not _IDENTIFIER.fullmatch(identifier):
            raise ValueError(f"非法的数据库标识符: {identifier!r}")

    engine = create_engine(settings.mysql_root_url)
    try:
        with engine.connect() as connection:
            connection.execute(
                text(f"CREATE USER IF NOT EXISTS '{user}'@'%' IDENTIFIED BY :password"),
                {"password": password},
            )
            # 重复执行时把密码对齐到当前配置。
            connection.execute(
                text(f"ALTER USER '{user}'@'%' IDENTIFIED BY :password"),
                {"password": password},
            )
            for view in ANALYTICS_VIEW_NAMES:
                connection.execute(
                    text(f"GRANT SELECT ON `{database}`.`{view}` TO '{user}'@'%'")
                )
            connection.execute(text("FLUSH PRIVILEGES"))
            connection.commit()
    finally:
        engine.dispose()


if __name__ == "__main__":
    setup_analytics_account(get_settings().database_url)
