"""语义视图与受限执行账号（ADR-0010、ADR-0025、ADR-0029 的地基）。

安全断言分三层：
- 结构层：执行账号对基础表无权限、对视图只读；
- 内容层：视图里没有敏感字段（身份证号、手机号、银行卡号、密码散列），返回结果里
  也不出现它们的值；姓名是例外——员工侧客户概况给出实名（ADR-0029），它是员工在
  工作台其他页面本来就看得见的信息，也只允许出现在那一张视图里；
- 行级层：员工侧按角色与归属关系收窄，客户域锁死为凭证客户本人，
  两域的身份未设置时都一行都看不到。
"""

import re
from collections.abc import Iterator

import pytest
from sqlalchemy import bindparam, create_engine, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import OperationalError, ProgrammingError

from app.agent.config import CUSTOMER_SERVICE_VIEW_NAMES
from app.analytics.catalog import VIEW_CATALOG
from app.auth.roles import ACCOUNT_MANAGER, ADVISOR, RISK_OFFICER
from app.db.analytics_account import (
    ANALYTICS_VIEW_NAMES,
    CUSTOMER_VIEW_NAMES,
    FULL_SCOPE_ROLES,
    analytics_url_for,
    apply_analytics_identity,
    apply_customer_identity,
    reset_analytics_identity,
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

# 种子数据里的 PII 值：任何一个出现在视图结果里都说明敏感字段漏进了视图。
SEED_PII_VALUES = (
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
)

# 种子客户姓名。ADR-0029 起员工侧的客户概况给出**实名**（它是员工在客户列表里本来就看
# 得见的信息，脱敏只让「客户王守成的持仓」这类问题必然问空），因此姓名只允许出现在
# `va_customer_overview` 里，其余视图（含客户域四张）一行都不许带。
SEED_CUSTOMER_NAMES = ("王守成", "李思远", "张衡", "赵启明", "钱远航")

ID_NUMBER_PATTERN = re.compile(r"\d{17}[\dXx]")
PHONE_PATTERN = re.compile(r"1\d{10}")

# 种子数据中的客户归属：manager1 与 manager2 各自名下的客户登录账号。
MANAGER1_CUSTOMERS = ("wangc1", "lisic2", "zhangc3")
MANAGER2_CUSTOMERS = ("zhaoc4", "qianc5")

# 客户域视图的两位客户：前者是默认的凭证客户，后者用来验「拿别人 id 也改不了范围」。
CUSTOMER = "wangc1"
OTHER_CUSTOMER = "lisic2"


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


@pytest.fixture
def customer_identity(
    app_connection: Connection, analytics_connection: Connection
) -> Connection:
    """以一位客户本人的身份设置好会话的执行账号连接（客户域的默认身份）。"""
    customer_id = _customer_id(app_connection, CUSTOMER)
    apply_customer_identity(analytics_connection, customer_id=customer_id)
    return analytics_connection


def _employee_id(connection: Connection, username: str) -> int:
    employee_id = connection.execute(
        text("SELECT id FROM sys_employee WHERE username = :username"),
        {"username": username},
    ).scalar_one()
    return int(employee_id)


def _customer_id(connection: Connection, username: str) -> int:
    return int(
        connection.execute(
            text("SELECT id FROM sys_customer WHERE username = :username"),
            {"username": username},
        ).scalar_one()
    )


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
                for secret in SEED_PII_VALUES:
                    assert secret not in rendered, f"{view} 泄露了种子 PII 值 {secret}"
                # 姓名的唯一出口是员工侧的客户概况（ADR-0029）。
                if view != "va_customer_overview":
                    for name in SEED_CUSTOMER_NAMES:
                        assert name not in rendered, f"{view} 出现了客户姓名 {name}"


def test_the_employee_overview_gives_the_real_customer_name(advisor_identity: Connection):
    """员工侧视图给出实名（迁移 0034、ADR-0029）。

    脱敏值挡不住任何东西——同一批姓名在客户列表、画像、预警里本来就看得见——却让
    「客户王守成的持仓情况」这类唯一的自然问法必然问空（生成的 `= '王守成'` 在「王**」
    上永远不成立，0 行又被解读成「该客户没有持仓」）。

    这是刻意的口径而不是漏掉的脱敏：想改回去要连迁移 0034 与本用例一起改，那是一次需要
    新 ADR 的改动（ADR-0029 的 Considered Options 记着被拒绝的几条备选）。
    """
    rows = advisor_identity.execute(
        text("SELECT customer_name FROM va_customer_overview")
    ).all()
    assert len(rows) == 5
    names = {name for (name,) in rows}
    assert names == set(SEED_CUSTOMER_NAMES)
    for name in names:
        assert "*" not in name


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


# ---- 客户域视图（ADR-0025）-----------------------------------------------------
#
# 行级范围锁死为凭证客户本人，未设置身份返回零行；本人数据不脱敏。两域各读各的
# 会话变量，因此哪一域的身份都打不开另一域的门。

# 合并读测试就地补的那笔转账与充值：固定的流水号让清理是确定的。
_TRANSFER_NO = "TV-CUSTOMER-VIEW-TEST-0001"
_DEPOSIT_NO = "DP-CUSTOMER-VIEW-TEST-0001"
_PAYEE_ACCOUNT = "6222020200112233445"


def _view_columns(connection: Connection, view: str) -> set[str]:
    rows = connection.execute(
        text(
            "SELECT column_name FROM information_schema.columns"
            " WHERE table_schema = DATABASE() AND table_name = :view"
        ),
        {"view": view},
    ).all()
    return {str(row[0]) for row in rows}


def _count_rows(connection: Connection, table: str, customer_id: int) -> int:
    return int(
        connection.execute(
            text(f"SELECT COUNT(*) FROM {table} WHERE customer_id = :customer_id"),
            {"customer_id": customer_id},
        ).scalar_one()
    )


def _flow_counts_by_base_tables(
    connection: Connection, customer_id: int
) -> dict[str, int]:
    """三类流水在基础表里的笔数：申赎按 `transaction_type` 分组，转账与充值各算一类。"""
    counts = {
        str(row[0]): int(row[1])
        for row in connection.execute(
            text(
                "SELECT transaction_type, COUNT(*) FROM fin_transaction"
                " WHERE customer_id = :customer_id GROUP BY transaction_type"
            ),
            {"customer_id": customer_id},
        ).all()
    }
    counts["转账"] = _count_rows(connection, "fin_transfer", customer_id)
    counts["充值"] = _count_rows(connection, "fin_deposit", customer_id)
    return {kind: count for kind, count in counts.items() if count}


def _flow_counts_in_view(connection: Connection) -> dict[str, int]:
    return {
        str(row[0]): int(row[1])
        for row in connection.execute(
            text(
                "SELECT transaction_type, COUNT(*) FROM va_my_transactions"
                " GROUP BY transaction_type"
            )
        ).all()
    }


def _delete_probe_flows(connection: Connection) -> None:
    """去掉合并读测试补的那两笔（上一次中断留下的也一并清掉）。"""
    connection.execute(
        text("DELETE FROM fin_transfer WHERE transfer_no = :no"), {"no": _TRANSFER_NO}
    )
    connection.execute(
        text("DELETE FROM fin_deposit WHERE deposit_no = :no"), {"no": _DEPOSIT_NO}
    )
    connection.commit()


def test_customer_views_fail_closed_without_identity(analytics_connection: Connection):
    # 不设会话身份的客户域视图一行都不返回——与员工侧同一条 fail-closed 语义。
    for view in CUSTOMER_VIEW_NAMES:
        count = analytics_connection.execute(text(f"SELECT COUNT(*) FROM {view}")).scalar_one()
        assert count == 0, f"{view} 在未设置身份时返回了数据"


def test_each_domain_reads_its_own_session_variable(
    app_connection: Connection, advisor_identity: Connection
):
    # advisor_identity 用的就是 analytics_connection：只有员工身份时，客户域视图零行……
    for view in CUSTOMER_VIEW_NAMES:
        assert advisor_identity.execute(text(f"SELECT COUNT(*) FROM {view}")).scalar_one() == 0
    # ……反过来，清掉员工身份、只设客户身份，员工侧带行级权限的视图同样零行。
    reset_analytics_identity(advisor_identity)
    apply_customer_identity(
        advisor_identity, customer_id=_customer_id(app_connection, CUSTOMER)
    )
    for view in (
        "va_customer_overview",
        "va_holding_distribution",
        "va_transaction_stat",
        "va_risk_alert_stat",
    ):
        assert advisor_identity.execute(text(f"SELECT COUNT(*) FROM {view}")).scalar_one() == 0


def test_customer_identity_locks_the_row_scope(
    app_connection: Connection, analytics_connection: Connection
):
    # 一位客户在自己的每一张视图里都只有自己的行，换一位客户就换一套行。
    for username in (CUSTOMER, OTHER_CUSTOMER):
        customer_id = _customer_id(app_connection, username)
        apply_customer_identity(analytics_connection, customer_id=customer_id)
        for view in CUSTOMER_VIEW_NAMES:
            assert _view_customer_ids(analytics_connection, view) == {customer_id}, view


def test_injected_customer_ids_cannot_widen_the_scope(
    app_connection: Connection, customer_identity: Connection
):
    # 行级条件内建在视图定义里，调用方的谓词只能再收窄：拿别人 id 去筛是零行，
    # 把它跟自己的 id 一起筛也只出自己的行——注入改不了范围。
    mine = _customer_id(app_connection, CUSTOMER)
    other = _customer_id(app_connection, OTHER_CUSTOMER)
    assert mine != other

    assert (
        customer_identity.execute(
            text("SELECT COUNT(*) FROM va_my_holdings WHERE customer_id = :other"),
            {"other": other},
        ).scalar_one()
        == 0
    )
    assert [
        tuple(row)
        for row in customer_identity.execute(
            text(
                "SELECT DISTINCT customer_id FROM va_my_holdings"
                " WHERE customer_id = :other OR 1 = 1"
            ),
            {"other": other},
        ).all()
    ] == [(mine,)]

    own_rows = customer_identity.execute(
        text("SELECT COUNT(*) FROM va_my_holdings")
    ).scalar_one()
    assert own_rows > 0
    assert (
        customer_identity.execute(
            text("SELECT COUNT(*) FROM va_my_holdings WHERE customer_id IN (:mine, :other)"),
            {"mine": mine, "other": other},
        ).scalar_one()
        == own_rows
    )


def test_customer_transaction_view_merges_all_three_sources(
    app_connection: Connection, customer_identity: Connection
):
    """申赎、转账、充值在同一张流水里：漏掉哪一段，那一类记录就整行消失。

    这正是 ADR-0019 的失败形态（当时漏掉的是转账）——查询照样成功，客户核对账目时
    却少看一笔。种子数据只有申赎，因此这里就地补一笔转账与一笔充值。
    """
    customer_id = _customer_id(app_connection, CUSTOMER)
    _delete_probe_flows(app_connection)
    app_connection.execute(
        text(
            "INSERT INTO fin_transfer"
            " (transfer_no, customer_id, amount, payee_name, payee_account, create_time)"
            " VALUES (:no, :customer_id, 1000.00, '视图测试收款人', :account, '2026-09-01 10:00:00')"
        ),
        {"no": _TRANSFER_NO, "customer_id": customer_id, "account": _PAYEE_ACCOUNT},
    )
    app_connection.execute(
        text(
            "INSERT INTO fin_deposit (deposit_no, customer_id, amount, create_time)"
            " VALUES (:no, :customer_id, 2000.00, '2026-09-02 10:00:00')"
        ),
        {"no": _DEPOSIT_NO, "customer_id": customer_id},
    )
    app_connection.commit()
    try:
        expected = _flow_counts_by_base_tables(app_connection, customer_id)
        assert {"申购", "转账", "充值"} <= set(expected)
        assert _flow_counts_in_view(customer_identity) == expected
        # 本人数据不脱敏：收款人账号原样返回，没有掩码。
        assert (
            customer_identity.execute(
                text(
                    "SELECT payee_account FROM va_my_transactions"
                    " WHERE transaction_no = :no"
                ),
                {"no": _TRANSFER_NO},
            ).scalar_one()
            == _PAYEE_ACCOUNT
        )
    finally:
        _delete_probe_flows(app_connection)


def test_risk_conclusion_view_holds_only_the_conclusion(
    app_connection: Connection, customer_identity: Connection
):
    # 只含等级结论列：总分与答题详情是内部研判材料，不在客户可见视图里。
    assert _view_columns(app_connection, "va_my_risk_assessment") == {
        "customer_id",
        "risk_level",
        "valid_until",
    }
    # 口径与 `find_current_result` 一致：同一客户取最后一条，历史测评不进视图。
    customer_id = _customer_id(app_connection, CUSTOMER)
    expected = app_connection.execute(
        text(
            "SELECT risk_level, valid_until FROM fin_risk_assessment"
            " WHERE customer_id = :customer_id ORDER BY id DESC LIMIT 1"
        ),
        {"customer_id": customer_id},
    ).one()
    actual = customer_identity.execute(
        text("SELECT risk_level, valid_until FROM va_my_risk_assessment")
    ).one()
    assert tuple(actual) == tuple(expected)


# ---- 列标签与视图列面一致（ADR-0028）--------------------------------------------
#
# 客户侧的结果表拿 `catalog.ViewSpec.column_labels` 当表头，缺标签的列在运行时回落
# 英文列名。这条断言把漂移挡在 CI 里：迁移给客户可见视图加了列，而目录没补中文表头，
# 客户就会在表头里读到 snake_case——那正是 ADR-0028 要避免的形态；反过来，标签键多于
# 实际列说明目录在描述一张不存在的表。**客户候选集里的每一张视图都算**：产品要素不是
# 客户域视图，但它在候选集里，客户问产品清单时它的表头同样可见。


def test_every_customer_facing_column_has_a_chinese_label(
    analytics_ready: str, app_connection: Connection
):
    specs = {spec.name: spec for spec in VIEW_CATALOG}
    assert set(CUSTOMER_SERVICE_VIEW_NAMES) <= set(specs), "客户候选集里出现了目录外的视图"
    for name in CUSTOMER_SERVICE_VIEW_NAMES:
        spec = specs[name]
        assert set(spec.column_labels) == _view_columns(app_connection, name), (
            f"{name} 的列面与 column_labels 不一致：迁移加了列就要在 catalog 里补表头"
        )
        for column, label in spec.column_labels.items():
            assert not any(
                character.isascii() and character.isalpha() for character in label
            ), f"{name}.{column} 的表头不是中文：{label}"
        # 视图自己的中文名：结果表的 `views` 用它，没有它就只能回落 `va_*`（客户不认）。
        assert spec.label and not any(
            character.isascii() and character.isalpha() for character in spec.label
        ), f"{name} 没有中文视图名"
