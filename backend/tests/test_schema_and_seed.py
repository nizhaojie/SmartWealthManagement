from decimal import Decimal

from sqlalchemy import create_engine, text

from app.db.migrate import apply_schema
from app.db.seed import seed
from app.settings import get_settings

EXPECTED_TABLES = {
    "sys_customer",
    "sys_employee",
    "fin_customer_profile",
    "fin_product",
    "fin_underlying_asset",
    "fin_product_underlying",
    "fin_transaction",
    "fin_holdings",
    "fin_risk_assessment",
    "fin_risk_alert",
    "biz_work_order",
    "conversation_archive",
    "fin_knowledge_meta",
}

CHINESE_GRADE_NAMES = ("保守型", "稳健型", "平衡型", "进取型", "激进型")


def _test_url() -> str:
    url = get_settings().test_database_url
    assert "wealth_test" in url
    return url


def _test_engine():
    return create_engine(_test_url())


def test_apply_schema_creates_the_identity_split_tables():
    apply_schema(_test_url())

    with _test_engine().connect() as connection:
        database = connection.execute(text("SELECT DATABASE()")).scalar()
        tables = {
            row[0]
            for row in connection.execute(text("SHOW TABLES")).fetchall()
        }

    assert database == "wealth_test"
    assert EXPECTED_TABLES <= tables
    assert "sys_user" not in tables
    assert "sys_customer" in tables
    assert "sys_employee" in tables


def test_apply_schema_can_be_run_twice_without_error():
    apply_schema(_test_url())
    apply_schema(_test_url())

    with _test_engine().connect() as connection:
        tables = {row[0] for row in connection.execute(text("SHOW TABLES")).fetchall()}
    assert EXPECTED_TABLES <= tables


def test_seed_loads_customers_catalog_holdings_and_transactions():
    apply_schema(_test_url())
    seed(_test_url())

    with _test_engine().connect() as connection:
        customers = connection.execute(text("SELECT COUNT(*) FROM sys_customer")).scalar()
        employees = connection.execute(text("SELECT COUNT(*) FROM sys_employee")).scalar()
        product_levels = {
            row[0]
            for row in connection.execute(text("SELECT DISTINCT risk_level FROM fin_product"))
        }
        holdings = connection.execute(text("SELECT COUNT(*) FROM fin_holdings")).scalar()
        transactions = connection.execute(text("SELECT COUNT(*) FROM fin_transaction")).scalar()
        assessments = connection.execute(
            text("SELECT COUNT(*) FROM fin_risk_assessment")
        ).scalar()
        plaintext = connection.execute(
            text("SELECT COUNT(*) FROM sys_customer WHERE password_hash = 'Test@1234'")
        ).scalar()

    assert customers == 5
    assert employees >= 3
    assert product_levels == {"R1", "R2", "R3", "R4", "R5"}
    assert holdings >= 5
    assert transactions >= 5
    assert assessments == 5
    assert plaintext == 0


def test_risk_grades_are_stored_as_codes_not_chinese_names():
    apply_schema(_test_url())
    seed(_test_url())

    with _test_engine().connect() as connection:
        customer_levels = [
            row[0]
            for row in connection.execute(text("SELECT risk_level FROM fin_customer_profile"))
        ]
        product_levels = [
            row[0] for row in connection.execute(text("SELECT risk_level FROM fin_product"))
        ]
        assessment_levels = [
            row[0]
            for row in connection.execute(text("SELECT risk_level FROM fin_risk_assessment"))
        ]

    for value in customer_levels + assessment_levels:
        assert value in {"C1", "C2", "C3", "C4", "C5"}
        assert value not in CHINESE_GRADE_NAMES
    for value in product_levels:
        assert value in {"R1", "R2", "R3", "R4", "R5"}
        assert value not in CHINESE_GRADE_NAMES


def test_schema_rejects_chinese_risk_grade_names():
    apply_schema(_test_url())
    seed(_test_url())

    with _test_engine().connect() as connection:
        trans = connection.begin()
        try:
            connection.execute(
                text("UPDATE fin_product SET risk_level = '保守型' WHERE product_code = 'F000001'")
            )
            trans.commit()
            rejected = False
        except Exception:
            trans.rollback()
            rejected = True

    assert rejected is True


def test_seed_data_is_business_coherent():
    apply_schema(_test_url())
    seed(_test_url())

    with _test_engine().connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT
                    c.username,
                    c.opened_at,
                    p.total_assets,
                    a.assessment_date,
                    MIN(t.create_time) AS first_trade,
                    MAX(t.amount) AS max_amount
                FROM sys_customer c
                JOIN fin_customer_profile p ON p.customer_id = c.id
                JOIN fin_risk_assessment a ON a.customer_id = c.id
                JOIN fin_transaction t ON t.customer_id = c.id
                GROUP BY c.id, c.username, c.opened_at, p.total_assets, a.assessment_date
                """
            )
        ).mappings().all()

    assert len(rows) == 5
    for row in rows:
        assert row["opened_at"] < row["first_trade"]
        assert row["assessment_date"] < row["first_trade"].date()
        assert Decimal(row["max_amount"]) <= Decimal(row["total_assets"]) * Decimal("1.2")

    with _test_engine().connect() as connection:
        holding_rows = connection.execute(
            text(
                """
                SELECT h.create_time AS holding_time, t.create_time AS trade_time
                FROM fin_holdings h
                JOIN fin_transaction t
                  ON t.customer_id = h.customer_id AND t.product_id = h.product_id
                """
            )
        ).mappings().all()
    assert holding_rows
    for row in holding_rows:
        assert row["holding_time"] == row["trade_time"]


def test_seed_can_be_run_twice_without_duplicating_rows():
    apply_schema(_test_url())
    seed(_test_url())
    seed(_test_url())

    with _test_engine().connect() as connection:
        customers = connection.execute(text("SELECT COUNT(*) FROM sys_customer")).scalar()
        products = connection.execute(text("SELECT COUNT(*) FROM fin_product")).scalar()
        holdings = connection.execute(text("SELECT COUNT(*) FROM fin_holdings")).scalar()
        transactions = connection.execute(text("SELECT COUNT(*) FROM fin_transaction")).scalar()
        assessments = connection.execute(
            text("SELECT COUNT(*) FROM fin_risk_assessment")
        ).scalar()
        employees = connection.execute(text("SELECT COUNT(*) FROM sys_employee")).scalar()

    assert customers == 5
    assert products == 7
    assert holdings == 5
    assert transactions == 5
    assert assessments == 5
    assert employees == 4


def test_schema_and_seed_target_the_test_database():
    apply_schema(_test_url())
    seed(_test_url())

    with _test_engine().connect() as connection:
        database = connection.execute(text("SELECT DATABASE()")).scalar()
        customers = connection.execute(text("SELECT COUNT(*) FROM sys_customer")).scalar()

    assert database == "wealth_test"
    assert customers == 5
    assert get_settings().database_url != _test_url()
    assert "wealth_test" not in get_settings().database_url
