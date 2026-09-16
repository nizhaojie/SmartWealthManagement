"""Seam 1：GraphRAG 编排——实体识别、多跳取材、四类静默降级（ticket 03）。

真实 Neo4j 容器，命名空间与 test_knowledge_graph_tools.py 共用
`test_neo4j_graph_namespace`，同样靠 autouse 的全量重建保证每个测试
看到的图谱状态一致。「GraphRAG 比纯向量检索更准」这类效果类命题不在
这里断言（spec 原话）——这里只验证识别、路由到正确的查询工具、
降级路径不出错三件事。
"""

import time

import pytest
from neo4j import GraphDatabase
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session as OrmSession

from app.db.models import Customer
from app.db.seed import seed
from app.knowledge_graph import graphrag, sync
from app.knowledge_graph.entities import extract_entities
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


@pytest.fixture(autouse=True)
def _rebuilt_graph(db_session, driver, namespace):
    sync.rebuild_graph(db_session, driver, namespace=namespace)


@pytest.fixture
def zhangc3_id(db_session):
    return db_session.scalar(select(Customer.id).where(Customer.username == "zhangc3"))


@pytest.fixture
def zhaoc4_id(db_session):
    return db_session.scalar(select(Customer.id).where(Customer.username == "zhaoc4"))


# ---------------------------------------------------------------------------
# 实体识别：gazetteer 匹配真实图节点，匹配不上的丢弃
# ---------------------------------------------------------------------------


def test_extract_entities_resolves_product_name_to_real_node(driver, namespace):
    with driver.session() as session:
        entities = session.execute_read(
            extract_entities, namespace, "天璇混合基金最近的表现怎么样"
        )

    assert [(e.entity_type, e.value, e.identifier) for e in entities] == [
        ("product", "天璇混合基金", "F000003")
    ]


def test_extract_entities_resolves_customer_name_and_risk_level(driver, namespace, zhangc3_id):
    with driver.session() as session:
        entities = session.execute_read(
            extract_entities, namespace, "张衡的风险等级是不是C3"
        )

    by_type = {e.entity_type: e for e in entities}
    assert by_type["customer"].identifier == zhangc3_id
    assert by_type["risk_level"].identifier == "C3"


def test_extract_entities_discards_text_with_no_matching_node(driver, namespace):
    with driver.session() as session:
        entities = session.execute_read(
            extract_entities, namespace, "阿尔法半人马座恒星系统的行星编号列表是什么"
        )

    assert entities == []


def test_extract_entities_resolves_fund_manager_name(driver, namespace):
    with driver.session() as session:
        entities = session.execute_read(extract_entities, namespace, "邵行管理的产品风险高不高")

    assert [(e.entity_type, e.identifier) for e in entities] == [("fund_manager", "邵行")]


# ---------------------------------------------------------------------------
# 编排：命中实体后走正确的多跳查询
# ---------------------------------------------------------------------------


def test_augment_with_graph_returns_passages_for_matched_product(driver, namespace):
    result = graphrag.augment_with_graph(
        driver,
        _FakeDbAlwaysIdle(),
        namespace=namespace,
        question="天璇混合基金主要投在哪些行业",
        timeout_seconds=5.0,
    )

    assert result.degraded is False
    assert result.matched_entities == [{"type": "product", "value": "天璇混合基金"}]
    contents = {passage.content for passage in result.passages}
    assert any("大盘蓝筹" in content for content in contents)
    assert any("利率债" in content for content in contents)


def test_augment_with_graph_returns_common_holdings_for_two_customers(
    driver, namespace, zhangc3_id, zhaoc4_id
):
    result = graphrag.augment_with_graph(
        driver,
        _FakeDbAlwaysIdle(),
        namespace=namespace,
        question="张衡和赵启明有没有共同持仓",
        timeout_seconds=5.0,
    )

    assert result.degraded is False
    assert {e["type"] for e in result.matched_entities} == {"customer"}
    # 张衡与赵启明按种子数据没有交叉持仓，共同持仓工具因此不产出段落，
    # 但各自的持仓与行业分布仍然应该被取到（客户实体本身命中了）。
    assert result.passages, "张衡自身的持仓/行业分布应当产出图谱段落"


# ---------------------------------------------------------------------------
# 四类静默降级
# ---------------------------------------------------------------------------


def test_augment_with_graph_degrades_silently_when_no_entity_matched(driver, namespace):
    result = graphrag.augment_with_graph(
        driver,
        _FakeDbAlwaysIdle(),
        namespace=namespace,
        question="阿尔法半人马座恒星系统的行星编号列表是什么",
        timeout_seconds=5.0,
    )

    assert result.degraded is True
    assert result.degradation_reason == graphrag.DEGRADED_NO_ENTITY
    assert result.passages == []


def test_augment_with_graph_degrades_silently_when_neo4j_unavailable(namespace):
    # max_transaction_retry_time 调小让驱动的内部重试尽快放弃（默认 30 秒重试会
    # 让这次连接失败在我们的软超时窗口内表现成 graph_query_timeout，而不是
    # 这个用例真正要测的 neo4j_unavailable）。
    unreachable_driver = GraphDatabase.driver(
        "bolt://127.0.0.1:1",
        auth=("neo4j", "wrong"),
        connection_timeout=1.0,
        max_transaction_retry_time=0.5,
    )
    try:
        result = graphrag.augment_with_graph(
            unreachable_driver,
            _FakeDbAlwaysIdle(),
            namespace=namespace,
            question="天璇混合基金主要投在哪些行业",
            timeout_seconds=10.0,
        )
    finally:
        unreachable_driver.close()

    assert result.degraded is True
    assert result.degradation_reason == graphrag.DEGRADED_UNAVAILABLE
    assert result.passages == []


def test_augment_with_graph_degrades_silently_on_timeout(driver, namespace, monkeypatch):
    def _slow_retrieval(*args, **kwargs):
        time.sleep(1.0)
        return [], []

    monkeypatch.setattr(graphrag, "_run_graph_retrieval", _slow_retrieval)

    result = graphrag.augment_with_graph(
        driver,
        _FakeDbAlwaysIdle(),
        namespace=namespace,
        question="天璇混合基金主要投在哪些行业",
        timeout_seconds=0.05,
    )

    assert result.degraded is True
    assert result.degradation_reason == graphrag.DEGRADED_TIMEOUT


def test_augment_with_graph_degrades_silently_when_rebuilding_without_old_graph(driver, namespace):
    result = graphrag.augment_with_graph(
        driver,
        _FakeDbRebuildingWithNoPriorSuccess(),
        namespace=namespace,
        question="天璇混合基金主要投在哪些行业",
        timeout_seconds=5.0,
    )

    assert result.degraded is True
    assert result.degradation_reason == graphrag.DEGRADED_REBUILDING


class _FakeDbAlwaysIdle:
    """替身：不查真实的 GraphSyncRun 表，直接把 get_status 短路成"无重建在跑"。"""


class _FakeDbRebuildingWithNoPriorSuccess:
    """替身：模拟"正在重建且从未有过成功重建"的状态。"""


def _fake_status_idle(_db):
    return {"running": False, "synced_at": None}


def _fake_status_rebuilding_without_old_graph(_db):
    return {"running": True, "synced_at": None}


@pytest.fixture(autouse=True)
def _patch_sync_status(monkeypatch):
    original = graphrag.sync_service.get_status

    def _dispatch(db):
        if isinstance(db, _FakeDbRebuildingWithNoPriorSuccess):
            return _fake_status_rebuilding_without_old_graph(db)
        if isinstance(db, _FakeDbAlwaysIdle):
            return _fake_status_idle(db)
        return original(db)

    monkeypatch.setattr(graphrag.sync_service, "get_status", _dispatch)
