"""语义视图与受限执行账号（ADR-0010 的地基）。

安全断言分两层：
- 结构层：执行账号对基础表无权限、对视图只读；
- 内容层：视图定义不含敏感字段，返回结果里也不出现敏感值；
- 行级层：客户经理只能看到自己名下客户的行，身份未设置时一行都看不到。
"""

import re
from collections.abc import Iterator

import pytest
from sqlalchemy import bindparam, create_engine, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import OperationalError, ProgrammingError

from app.auth.roles import ACCOUNT_MANAGER, ADVISOR, RISK_OFFICER
from app.db.analytics_account import (
    ANALYTICS_VIEW_NAMES,
    FULL_SCOPE_ROLES,
    analytics_url_for,
    apply_analytics_identity,
    setup_analytics_account,
)
from app.db.migrate import apply_schema
from app.db.seed import seed
from app.settings import get_settings

BASE_TABLES = (
    "sys_customer",
    "sys_employee",
    "fin_customer_profile",
    "fin_profile_tag",
    "fin_profile_tag_conflict",
    "fin_product",
    "fin_underlying_asset",
    "fin_product_underlying",
    "fin_transaction",
    "fin_holdings",
    "fin_risk_assessment",
    "fin_suitability_decision",
    "fin_risk_alert",
    "biz_work_order",
    "biz_advisory_request",
    "conversation_archive",
    "fin_knowledge_meta",
)

SENSITIVE_COLUMN_NAMES = {"id_number", "phone", "password_hash", "real_name", "bank_card"}

# 种子数据里的真实敏感值：任何一个出现在视图结果里都说明脱敏漏了。
SEED_SECRETS = (
    "110101198803150218",
    "310101197605220353",
    "440106199211080474",
    "320106198412030121",
    "110105199508180297",
    "13800138001",
    "13800138002",
    "13800138003",
    "13800138004",
    "13800138005",
    "王守成",
    "李思远",
    "张衡",
    "赵启明",
    "钱远航",
)

ID_NUMBER_PATTERN = re.compile(r"\d{17}[\dXx]")
PHONE_PATTERN = re.compile(r"1\d{10}")

# 种子数据中的客户归属：manager1 与 manager2 各自名下的客户登录账号。
MANAGER1_CUSTOMERS = ("wangc1", "lisic2", "zhangc3")
MANAGER2_CUSTOMERS = ("zhaoc4", "qianc5")


@pytest.fixture(scope="module")
def analytics_ready() -> str:
    settings = get_settings()
    url = settings.test_database_url
    apply_schema(url)
    seed(url)
    setup_analytics_account(url)
    return url


@pytest.fixture
def app_connection(analytics_ready: str) -> Iterator[Connection]:
    engine = create_engine(analytics_ready)
    with engine.connect() as connection:
        yield connection
    engine.dispose()


@pytest.fixture
def analytics_connection(analytics_ready: str) -> Iterator[Connection]:
    settings = get_settings()
    engine = create_engine(
        analytics_url_for(analytics_ready, settings.analytics_db_user, settings.analytics_db_password)
    )
    with engine.connect() as connection:
        yield connection
    engine.dispose()


@pytest.fixture
def advisor_identity(
    app_connection: Connection, analytics_connection: Connection
) -> Connection:
    """以理财顾问（全量行级范围）身份设置好会话的执行账号连接。"""
    advisor_id = _employee_id(app_connection, "advisor1")
    apply_analytics_identity(analytics_connection, employee_id=advisor_id, role=ADVISOR)
    return analytics_connection


def _employee_id(connection: Connection, username: str) -> int:
    employee_id = connection.execute(
        text("SELECT id FROM sys_employee WHERE username = :username"),
        {"username": username},
    ).scalar_one()
    return int(employee_id)


def _customer_ids_by_username(connection: Connection, usernames: tuple[str, ...]) -> set[int]:
    rows = connection.execute(
        text("SELECT id FROM sys_customer WHERE username IN :usernames").bindparams(
            bindparam("usernames", expanding=True)
        ),
        {"usernames": usernames},
    ).all()
    return {int(row[0]) for row in rows}


def _view_customer_ids(connection: Connection, view: str) -> set[int]:
    rows = connection.execute(text(f"SELECT DISTINCT customer_id FROM {view}")).all()
    return {int(row[0]) for row in rows}


def test_semantic_views_exist_and_match_the_grant_list(
    analytics_ready: str, app_connection: Connection
):
    rows = app_connection.execute(
        text(
            "SELECT table_name FROM information_schema.views"
            " WHERE table_schema = DATABASE()"
        )
    ).all()
    view_names = {row[0] for row in rows}
    # 授权清单与迁移创建的视图必须一致，否则会出现「视图存在但账号没权限」或反之。
    assert view_names == set(ANALYTICS_VIEW_NAMES)


def test_analytics_account_can_read_every_view(advisor_identity: Connection):
    for view in ANALYTICS_VIEW_NAMES:
        advisor_identity.execute(text(f"SELECT COUNT(*) FROM {view}")).scalar_one()


def test_analytics_account_is_denied_on_every_base_table(analytics_connection: Connection):
    for table in BASE_TABLES:
        with pytest.raises(OperationalError):
            analytics_connection.execute(text(f"SELECT * FROM {table} LIMIT 1"))


def test_analytics_account_cannot_write_through_views(analytics_connection: Connection):
    with pytest.raises(OperationalError):
        analytics_connection.execute(
            text("UPDATE va_product_element SET product_name = 'x' WHERE product_code = 'F000001'")
        )
    with pytest.raises(OperationalError):
        analytics_connection.execute(
            text("DELETE FROM va_product_element WHERE product_code = 'F000001'")
        )


def test_view_columns_exclude_sensitive_fields(
    analytics_ready: str, app_connection: Connection
):
    rows = app_connection.execute(
        text(
            "SELECT table_name, column_name FROM information_schema.columns"
            " WHERE table_schema = DATABASE() AND table_name IN :views"
        ).bindparams(bindparam("views", expanding=True)),
        {"views": ANALYTICS_VIEW_NAMES},
    ).all()
    columns = {(row[0], row[1].lower()) for row in rows}
    for view, column in columns:
        assert column not in SENSITIVE_COLUMN_NAMES, f"{view}.{column} 是敏感字段"
        assert "password" not in column and "id_number" not in column


def test_view_rows_contain_no_sensitive_values(advisor_identity: Connection):
    for view in ANALYTICS_VIEW_NAMES:
        rows = advisor_identity.execute(text(f"SELECT * FROM {view}")).mappings().all()
        for row in rows:
            for value in row.values():
                if value is None:
                    continue
                rendered = str(value)
                assert not ID_NUMBER_PATTERN.search(rendered), f"{view} 出现身份证号样式: {rendered}"
                assert not PHONE_PATTERN.search(rendered), f"{view} 出现手机号: {rendered}"
                for secret in SEED_SECRETS:
                    assert secret not in rendered, f"{view} 泄露了种子敏感值 {secret}"


def test_customer_names_are_masked_in_views(advisor_identity: Connection):
    rows = advisor_identity.execute(
        text("SELECT customer_name FROM va_customer_overview")
    ).all()
    assert len(rows) == 5
    for (name,) in rows:
        assert name.endswith("*" * (len(name) - 1))
        assert name not in SEED_SECRETS


def test_account_manager_sees_only_own_customers(
    analytics_ready: str, app_connection: Connection, analytics_connection: Connection
):
    manager1_id = _employee_id(app_connection, "manager1")
    manager2_id = _employee_id(app_connection, "manager2")
    manager1_customers = _customer_ids_by_username(app_connection, MANAGER1_CUSTOMERS)
    manager2_customers = _customer_ids_by_username(app_connection, MANAGER2_CUSTOMERS)
    assert manager1_customers and manager2_customers
    assert manager1_customers.isdisjoint(manager2_customers)

    apply_analytics_identity(analytics_connection, employee_id=manager1_id, role=ACCOUNT_MANAGER)
    assert _view_customer_ids(analytics_connection, "va_customer_overview") == manager1_customers
    assert _view_customer_ids(analytics_connection, "va_holding_distribution") == manager1_customers
    assert _view_customer_ids(analytics_connection, "va_transaction_stat") == manager1_customers

    apply_analytics_identity(analytics_connection, employee_id=manager2_id, role=ACCOUNT_MANAGER)
    assert _view_customer_ids(analytics_connection, "va_customer_overview") == manager2_customers
    assert _view_customer_ids(analytics_connection, "va_holding_distribution") == manager2_customers
    assert _view_customer_ids(analytics_connection, "va_transaction_stat") == manager2_customers


def test_full_scope_roles_match_the_view_definition():
    # 视图定义里的角色字面量（迁移 0008）与执行层常量必须一致，
    # 漂移会让全量范围角色静默退化成零行。
    assert set(FULL_SCOPE_ROLES) == {ADVISOR, RISK_OFFICER}
    assert ACCOUNT_MANAGER not in FULL_SCOPE_ROLES


def test_advisor_and_risk_officer_have_full_row_scope(
    analytics_ready: str, app_connection: Connection, analytics_connection: Connection
):
    all_customers = _customer_ids_by_username(
        app_connection, MANAGER1_CUSTOMERS + MANAGER2_CUSTOMERS
    )
    for username, role in (("advisor1", ADVISOR), ("risk1", RISK_OFFICER)):
        assert role in FULL_SCOPE_ROLES
        employee_id = _employee_id(app_connection, username)
        apply_analytics_identity(analytics_connection, employee_id=employee_id, role=role)
        assert _view_customer_ids(analytics_connection, "va_customer_overview") == all_customers
        assert _view_customer_ids(analytics_connection, "va_holding_distribution") == all_customers


def test_unset_identity_fails_closed(analytics_connection: Connection):
    # 不设会话身份时，任何带行级权限的视图都必须返回零行——宁可答不上来。
    for view in ("va_customer_overview", "va_holding_distribution", "va_transaction_stat", "va_risk_alert_stat"):
        count = analytics_connection.execute(text(f"SELECT COUNT(*) FROM {view}")).scalar_one()
        assert count == 0, f"{view} 在未设置身份时返回了数据"


def test_multi_statement_role_escalation_is_rejected(advisor_identity: Connection):
    # 行级权限的前提是模型生成的语句不能自己 SET 会话变量提权。
    # 驱动层默认不开多语句，「SET ...; SELECT ...」在解析期即被拒绝——
    # 这条护栏固定该前提；ticket 02 的校验层在其之上再挡一次。
    with pytest.raises((OperationalError, ProgrammingError)):
        advisor_identity.execute(
            text(
                "SET @analytics_employee_role = '理财顾问';"
                " SELECT COUNT(*) FROM va_customer_overview"
            )
        )


def test_asset_scale_is_a_fixed_definition_not_caller_aggregation(
    analytics_ready: str, app_connection: Connection, advisor_identity: Connection
):
    # 口径固定：资产规模 = 该客户「持有中」持仓的当前市值合计，无持仓为 0。
    expected = {
        int(row[0]): row[1]
        for row in app_connection.execute(
            text(
                "SELECT c.id, COALESCE(SUM(CASE WHEN h.status = '持有中'"
                " THEN h.current_value END), 0)"
                " FROM sys_customer c"
                " LEFT JOIN fin_holdings h ON h.customer_id = c.id"
                " GROUP BY c.id"
            )
        ).all()
    }
    rows = advisor_identity.execute(
        text("SELECT customer_id, asset_scale FROM va_customer_overview")
    ).all()
    actual = {int(row[0]): row[1] for row in rows}
    assert actual == expected
