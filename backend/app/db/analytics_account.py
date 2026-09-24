"""受限执行账号与语义视图清单（ADR-0010、ADR-0025 的地基）。

安全性由结构保证：
- 语义视图由迁移脚本创建（员工侧见 migrations/versions/0008，客户域见 0030），
  本模块的两个视图名清单是授权清单，有测试保证它们的并集与迁移创建的视图集合一致；
- 执行账号 ``wealth_analytics`` 只对这组视图有 SELECT 权限，对基础表无任何权限；
- 行级权限内建在视图定义中，分两域：员工侧视图通过 ``analytics_employee_id()`` /
  ``analytics_employee_role()`` 读会话变量，客户域视图通过 ``analytics_customer_id()``
  读会话变量。执行查询前必须在同一连接上用 ``apply_identity`` 设置 ``AnalyticsIdentity``
  （员工或客户，见下）；未设置身份时视图返回零行（fail closed）。两域各读各的变量，
  因此一身员工身份查不到客户域的行，反之亦然。
"""

import re
from dataclasses import dataclass

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, make_url

from app.auth.roles import ADVISOR, RISK_OFFICER
from app.settings import get_settings

_IDENTIFIER = re.compile(r"[A-Za-z0-9_]+")

# 员工侧视图：行级范围由角色与归属关系决定（迁移 0008）。
EMPLOYEE_VIEW_NAMES: tuple[str, ...] = (
    "va_customer_overview",
    "va_holding_distribution",
    "va_transaction_stat",
    "va_product_element",
    "va_risk_alert_stat",
)

# 客户域视图：行级范围锁死为凭证客户本人（迁移 0030，ADR-0025）。
CUSTOMER_VIEW_NAMES: tuple[str, ...] = (
    "va_my_holdings",
    "va_my_transactions",
    "va_my_funding_account",
    "va_my_risk_assessment",
)

# 授权清单：受限账号对这组视图有 SELECT。两域两套视图，互相独立。
ANALYTICS_VIEW_NAMES: tuple[str, ...] = EMPLOYEE_VIEW_NAMES + CUSTOMER_VIEW_NAMES

# 拥有全量行级范围的角色；客户经理不在其中，只能看到名下客户。
# 视图定义里是同样的字面量，此处用于执行层判断与测试对照。
FULL_SCOPE_ROLES: tuple[str, ...] = (ADVISOR, RISK_OFFICER)


def analytics_url_for(base_url: str, user: str, password: str) -> str:
    """把任意数据库连接的账号换成执行账号，库名与其余参数保持不变。"""
    return make_url(base_url).set(username=user, password=password).render_as_string(
        hide_password=False
    )


@dataclass(frozen=True)
class AnalyticsIdentity:
    """一次受限查询的行级身份：员工或客户（ADR-0025）。

    两种身份各读各的会话变量，因此互斥而不是叠加——一位客户拿到员工身份，或一位员工
    拿到客户身份，都只会让另一域的视图返回零行（fail closed 的语义在视图定义里，这里
    只负责把身份如实写进连接）。构造只走两个命名构造器，避免「两个都填」这类没有含义
    的状态在调用点被顺手拼出来。
    """

    employee_id: int | None = None
    role: str | None = None
    customer_id: int | None = None

    @classmethod
    def employee(cls, *, employee_id: int, role: str) -> "AnalyticsIdentity":
        return cls(employee_id=employee_id, role=role)

    @classmethod
    def customer(cls, *, customer_id: int) -> "AnalyticsIdentity":
        return cls(customer_id=customer_id)


def apply_identity(connection: Connection, identity: AnalyticsIdentity) -> None:
    """把身份写进连接：客户身份走客户域变量，员工身份走员工域那两个变量。

    两样都没给时抛错而不是照写 NULL：身份写空的后果是每张视图都返回零行，那会
    表现成「查得到但结果为空」这种最像数据问题、最不像程序问题的失败。
    """
    if identity.customer_id is not None:
        apply_customer_identity(connection, customer_id=identity.customer_id)
        return
    if identity.employee_id is None or identity.role is None:
        raise ValueError("员工身份必须同时给出 employee_id 与 role")
    apply_analytics_identity(
        connection, employee_id=identity.employee_id, role=identity.role
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


def apply_customer_identity(connection: Connection, *, customer_id: int) -> None:
    """在连接上设置当前客户身份：客户域视图只返回这位客户自己的行。

    与员工身份分开的会话变量（``@analytics_customer_id``）：一位客户拿到员工身份、
    或一位员工拿到客户身份，都只会让另一域的视图返回零行。设置与清理的时机同
    ``apply_analytics_identity``——必须在执行查询的同一连接上设置，归还连接池前
    ``reset_analytics_identity``。
    """
    connection.execute(
        text("SET @analytics_customer_id = :customer_id"), {"customer_id": customer_id}
    )


def reset_analytics_identity(connection: Connection) -> None:
    """清空连接上的两域身份，回到 fail-closed 状态（视图返回零行）。

    两域变量一起清：只清一域的话，下一个借用该连接的请求会继承另一个域的身份。
    """
    connection.execute(text("SET @analytics_employee_id = NULL"))
    connection.execute(text("SET @analytics_employee_role = NULL"))
    connection.execute(text("SET @analytics_customer_id = NULL"))


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
