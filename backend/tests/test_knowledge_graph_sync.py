"""Seam 1：MySQL → Neo4j 全量重建，真实容器（ADR-0002）。

覆盖 ticket 01 的核心断言：重建幂等、统计吻合源数据、图谱结构支持多跳
查询、失败时旧图谱不受影响。查询工具本身（参数契约、拒绝非法输入）是
ticket 02 的范围，这里只验证图谱模型撑得住多跳，不封装成 Agent 工具。
"""

import pytest
from neo4j import GraphDatabase
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session as OrmSession

from app.db.models import Customer, Holding, Product
from app.db.seed import seed
from app.knowledge_graph import sync
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


def _snapshot(driver, namespace: str) -> tuple[frozenset, frozenset]:
    with driver.session() as session:
        node_rows = session.run(
            "MATCH (n {namespace: $ns}) "
            "RETURN labels(n) AS labels, properties(n) AS props",
            ns=namespace,
        )
        nodes = frozenset(
            (tuple(sorted(row["labels"])), tuple(sorted(row["props"].items())))
            for row in node_rows
        )
        rel_rows = session.run(
            "MATCH (a {namespace: $ns})-[r]->(b {namespace: $ns}) "
            "RETURN type(r) AS type, properties(a) AS a_props, properties(b) AS b_props, "
            "properties(r) AS r_props",
            ns=namespace,
        )
        rels = frozenset(
            (
                row["type"],
                tuple(sorted(row["a_props"].items())),
                tuple(sorted(row["b_props"].items())),
                tuple(sorted(row["r_props"].items())),
            )
            for row in rel_rows
        )
    return nodes, rels


def _count_in_neo4j(driver, namespace: str) -> tuple[int, int]:
    with driver.session() as session:
        node_count = session.run(
            "MATCH (n {namespace: $ns}) RETURN count(n) AS c", ns=namespace
        ).single()["c"]
        rel_count = session.run(
            "MATCH ()-[r {namespace: $ns}]->() RETURN count(r) AS c", ns=namespace
        ).single()["c"]
    return node_count, rel_count


def test_rebuild_is_idempotent(db_session, driver, namespace):
    stats_first = sync.rebuild_graph(db_session, driver, namespace=namespace)
    nodes_first, rels_first = _snapshot(driver, namespace)

    stats_second = sync.rebuild_graph(db_session, driver, namespace=namespace)
    nodes_second, rels_second = _snapshot(driver, namespace)

    assert stats_first == stats_second
    assert nodes_first == nodes_second
    assert rels_first == rels_second


def test_rebuild_stats_match_source(db_session, driver, namespace):
    stats = sync.rebuild_graph(db_session, driver, namespace=namespace)

    node_count, rel_count = _count_in_neo4j(driver, namespace)
    assert stats["node_count"] == node_count
    assert stats["relationship_count"] == rel_count

    customers = db_session.execute(select(Customer.id)).all()
    products = db_session.execute(select(Product.id)).all()
    # 五类节点：客户、产品、风险等级（固定 5 档）、行业、基金经理——
    # 客户与产品数直接来自源表，行业/基金经理数量随源数据变化，这里只锁定下限。
    assert stats["node_count"] >= len(customers) + len(products) + 5


def test_multihop_customer_holding_industries(db_session, driver, namespace):
    sync.rebuild_graph(db_session, driver, namespace=namespace)
    customer_id = db_session.scalar(
        select(Customer.id).where(Customer.username == "zhangc3")
    )

    with driver.session() as session:
        rows = session.run(
            "MATCH (c:Customer {namespace: $ns, customer_id: $id})"
            "-[:HOLDS]->(:Product)-[:BELONGS_TO_INDUSTRY]->(i:Industry) "
            "RETURN DISTINCT i.name AS industry ORDER BY industry",
            ns=namespace,
            id=customer_id,
        )
        industries = {row["industry"] for row in rows}

    # zhangc3 持有 F000003，直接底层资产落在 EQTY-0001（大盘蓝筹）与
    # BOND-0001（利率债）——见 app/db/seed.py 的 _PRODUCT_UNDERLYINGS。
    assert industries == {"大盘蓝筹", "利率债"}


def test_multihop_fund_manager_products(db_session, driver, namespace):
    sync.rebuild_graph(db_session, driver, namespace=namespace)

    with driver.session() as session:
        rows = session.run(
            "MATCH (:FundManager {namespace: $ns, name: '邵行'})<-[:MANAGED_BY]-(p:Product) "
            "RETURN p.product_code AS code ORDER BY code",
            ns=namespace,
        )
        codes = [row["code"] for row in rows]

    # 邵行在种子数据里管理两只互为底层的 FOF（F900001/F900002），见 seed.py 注释。
    assert codes == ["F900001", "F900002"]


def test_multihop_common_holdings_between_customers(db_session, driver, namespace):
    """种子数据里每位客户只持有一只不同的产品，先补一条重叠持仓再验证共同持仓查询。"""
    zhangc3_id = db_session.scalar(select(Customer.id).where(Customer.username == "zhangc3"))
    zhaoc4_id = db_session.scalar(select(Customer.id).where(Customer.username == "zhaoc4"))
    f000003_id = db_session.scalar(select(Product.id).where(Product.product_code == "F000003"))

    extra = db_session.scalar(
        select(Holding).where(Holding.customer_id == zhaoc4_id, Holding.product_id == f000003_id)
    )
    if extra is None:
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

    try:
        sync.rebuild_graph(db_session, driver, namespace=namespace)

        with driver.session() as session:
            rows = session.run(
                "MATCH (a:Customer {namespace: $ns, customer_id: $a_id})-[:HOLDS]->(p:Product)"
                "<-[:HOLDS]-(b:Customer {namespace: $ns, customer_id: $b_id}) "
                "RETURN p.product_code AS code",
                ns=namespace,
                a_id=zhangc3_id,
                b_id=zhaoc4_id,
            )
            codes = {row["code"] for row in rows}

        assert codes == {"F000003"}
    finally:
        db_session.execute(
            Holding.__table__.delete().where(
                Holding.customer_id == zhaoc4_id, Holding.product_id == f000003_id
            )
        )
        db_session.commit()
        sync.rebuild_graph(db_session, driver, namespace=namespace)


def test_rebuild_failure_leaves_old_graph_intact(db_session, driver, namespace, monkeypatch):
    sync.rebuild_graph(db_session, driver, namespace=namespace)
    nodes_before, rels_before = _snapshot(driver, namespace)

    original = sync._load_projection

    def _poisoned(db):
        projection = original(db)
        # Neo4j 驱动不接受 Decimal 参数，这个非法行会在 Industry 这一步的
        # tx.run 里触发客户端序列化错误——此时 Customer/Product/RiskLevel
        # 已经在同一个写事务里 CREATE 过了，用来验证失败会整体回滚。
        from decimal import Decimal

        projection.industries = projection.industries + [Decimal("1")]
        return projection

    monkeypatch.setattr(sync, "_load_projection", _poisoned)

    with pytest.raises(Exception):
        sync.rebuild_graph(db_session, driver, namespace=namespace)

    monkeypatch.setattr(sync, "_load_projection", original)
    nodes_after, rels_after = _snapshot(driver, namespace)

    assert nodes_after == nodes_before
    assert rels_after == rels_before
