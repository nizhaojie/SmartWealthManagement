"""Seam 1：图谱查询工具，真实 Neo4j 容器（ticket 02，spec「查询工具」）。

覆盖六个工具各自的正确返回、三个多跳场景（行业分布/共同持仓/基金经理关联）、
以及工具拒绝超出参数契约的输入。查询语句是否正确已经由
test_knowledge_graph_sync.py 的多跳断言验证过一次，这里换成通过工具函数
（而不是裸 Cypher）驱动，确认封装本身behaves一致。
"""

import pytest
from neo4j import GraphDatabase
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session as OrmSession

from app.db.models import Customer, Holding, Product
from app.db.seed import seed
from app.exceptions import AppError
from app.knowledge_graph import sync, tools
from app.settings import get_settings


@pytest.fixture(scope="module")
def db_session():
    settings = get_settings()
    seed(settings.test_database_url)
    engine = create_engine(settings.test_database_url)
    with OrmSession(engine) as session:
        yield session
    engine.dispose()


@pytest.fixture(scope="module")
def driver():
    settings = get_settings()
    drv = GraphDatabase.driver(
        settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password)
    )
    yield drv
    drv.close()


@pytest.fixture
def namespace():
    return get_settings().test_neo4j_graph_namespace


@pytest.fixture
def zhangc3_id(db_session):
    return db_session.scalar(select(Customer.id).where(Customer.username == "zhangc3"))


@pytest.fixture
def zhaoc4_id(db_session):
    return db_session.scalar(select(Customer.id).where(Customer.username == "zhaoc4"))


@pytest.fixture(autouse=True)
def _rebuilt_graph(db_session, driver, namespace):
    sync.rebuild_graph(db_session, driver, namespace=namespace)


def test_customer_holdings_returns_held_products(driver, namespace, zhangc3_id):
    result = tools.customer_holdings(driver, namespace=namespace, customer_id=zhangc3_id)

    assert [row.product_code for row in result] == ["F000003"]
    assert result[0].product_name == "天璇混合基金"
    assert result[0].market_value == pytest.approx(108000.0)


def test_customer_holdings_rejects_non_positive_customer_id(driver, namespace):
    with pytest.raises(AppError) as excinfo:
        tools.customer_holdings(driver, namespace=namespace, customer_id=0)
    assert excinfo.value.code == 400

    with pytest.raises(AppError):
        tools.customer_holdings(driver, namespace=namespace, customer_id=-5)


def test_customer_holdings_unknown_customer_returns_empty(driver, namespace):
    result = tools.customer_holdings(driver, namespace=namespace, customer_id=999_999_999)
    assert result == []


def test_product_industries_returns_direct_underlying_industries(driver, namespace):
    result = tools.product_industries(driver, namespace=namespace, product_code="F000003")

    industries = {row.industry: row.weight for row in result}
    assert industries == {"大盘蓝筹": pytest.approx(0.4), "利率债": pytest.approx(0.2)}


def test_product_industries_rejects_empty_product_code(driver, namespace):
    with pytest.raises(AppError) as excinfo:
        tools.product_industries(driver, namespace=namespace, product_code="  ")
    assert excinfo.value.code == 400


def test_products_for_risk_level_returns_suitable_products(driver, namespace):
    result = tools.products_for_risk_level(driver, namespace=namespace, risk_level="C3")

    expected = {"F000001", "F000002", "F000003", "F900001", "F900002"}
    assert {row.product_code for row in result} == expected


def test_products_for_risk_level_rejects_unknown_code(driver, namespace):
    with pytest.raises(AppError) as excinfo:
        tools.products_for_risk_level(driver, namespace=namespace, risk_level="X9")
    assert excinfo.value.code == 400

    # 只接受客户风险等级代码（C1..C5），产品风险等级代码（R1..R5）不在这个工具的参数契约内。
    with pytest.raises(AppError):
        tools.products_for_risk_level(driver, namespace=namespace, risk_level="R3")


def test_multihop_customer_industry_exposure(driver, namespace, zhangc3_id):
    result = tools.customer_industry_exposure(driver, namespace=namespace, customer_id=zhangc3_id)

    by_industry = {row.industry: row for row in result}
    assert by_industry["大盘蓝筹"].exposure == pytest.approx(43200.0)
    assert by_industry["利率债"].exposure == pytest.approx(21600.0)
    assert by_industry["大盘蓝筹"].share == pytest.approx(2 / 3)
    assert by_industry["利率债"].share == pytest.approx(1 / 3)
    assert result[0].industry == "大盘蓝筹"  # 按 exposure 降序


def test_customer_industry_exposure_no_holdings_returns_empty(driver, namespace):
    empty_customer_id = 999_999_998
    result = tools.customer_industry_exposure(
        driver, namespace=namespace, customer_id=empty_customer_id
    )
    assert result == []


def test_multihop_common_holdings_between_customers(
    db_session, driver, namespace, zhangc3_id, zhaoc4_id
):
    f000003_id = db_session.scalar(select(Product.id).where(Product.product_code == "F000003"))
    db_session.add(
        Holding(
            customer_id=zhaoc4_id,
            product_id=f000003_id,
            shares="1000.0000",
            cost_amount="1000.00",
            current_value="1000.00",
            profit_loss="0.00",
            profit_ratio="0.0000",
            status="持有中",
        )
    )
    db_session.commit()
    sync.rebuild_graph(db_session, driver, namespace=namespace)

    try:
        result = tools.common_holdings(
            driver, namespace=namespace, customer_id_a=zhangc3_id, customer_id_b=zhaoc4_id
        )
        assert [row.product_code for row in result] == ["F000003"]

        reversed_result = tools.common_holdings(
            driver, namespace=namespace, customer_id_a=zhaoc4_id, customer_id_b=zhangc3_id
        )
        assert [row.product_code for row in reversed_result] == ["F000003"]
    finally:
        db_session.execute(
            Holding.__table__.delete().where(
                Holding.customer_id == zhaoc4_id, Holding.product_id == f000003_id
            )
        )
        db_session.commit()


def test_common_holdings_without_overlap_returns_empty(driver, namespace, zhangc3_id, zhaoc4_id):
    result = tools.common_holdings(
        driver, namespace=namespace, customer_id_a=zhangc3_id, customer_id_b=zhaoc4_id
    )
    assert result == []


def test_common_holdings_rejects_same_customer(driver, namespace, zhangc3_id):
    with pytest.raises(AppError) as excinfo:
        tools.common_holdings(
            driver, namespace=namespace, customer_id_a=zhangc3_id, customer_id_b=zhangc3_id
        )
    assert excinfo.value.code == 400


def test_multihop_fund_manager_products(driver, namespace):
    result = tools.fund_manager_products(driver, namespace=namespace, fund_manager="邵行")
    assert [row.product_code for row in result] == ["F900001", "F900002"]


def test_fund_manager_products_rejects_empty_name(driver, namespace):
    with pytest.raises(AppError) as excinfo:
        tools.fund_manager_products(driver, namespace=namespace, fund_manager="")
    assert excinfo.value.code == 400


def test_fund_manager_products_unknown_manager_returns_empty(driver, namespace):
    result = tools.fund_manager_products(driver, namespace=namespace, fund_manager="不存在的经理")
    assert result == []
