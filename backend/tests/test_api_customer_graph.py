"""Seam 1：客户关系图的可视化接口（ticket 04，spec「图谱关系图界面」）。

覆盖默认两跳（客户→产品→行业）、集中度超阈值标记、按需展开基金经理这一跳、
空图（客户未同步/无持仓）、参数校验、未授权拒绝，以及同步时间与
`GET /api/internal/graph/stats` 保持同一个真相来源。

图谱数据本身的正确性（六个查询工具、多跳场景）已经由
test_knowledge_graph_tools.py 覆盖，这里只验证组装成节点/连线之后的形状。
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session as OrmSession

from app.db.models import Customer
from app.db.seed import seed
from app.main import app
from app.settings import get_settings

EMPLOYEE_USERNAME = "advisor1"
SEEDED_PASSWORD = "Test@1234"


@pytest.fixture
def graph_client(auth_client: TestClient) -> Iterator[TestClient]:
    base_settings = get_settings()
    test_settings = base_settings.model_copy(
        update={"neo4j_graph_namespace": base_settings.test_neo4j_graph_namespace}
    )
    app.dependency_overrides[get_settings] = lambda: test_settings
    try:
        yield auth_client
    finally:
        app.dependency_overrides.pop(get_settings, None)


@pytest.fixture(scope="module")
def db_session() -> Iterator[OrmSession]:
    settings = get_settings()
    seed(settings.test_database_url)
    engine = create_engine(settings.test_database_url)
    with OrmSession(engine) as session:
        yield session
    engine.dispose()


def _internal_token(client: TestClient) -> str:
    response = client.post(
        "/api/internal/auth/login",
        json={"username": EMPLOYEE_USERNAME, "password": SEEDED_PASSWORD},
    )
    return response.json()["data"]["access_token"]


def _auth_headers(client: TestClient) -> dict[str, str]:
    return {"Authorization": f"Bearer {_internal_token(client)}"}


@pytest.fixture(autouse=True)
def _rebuilt_graph(db_session, graph_client):
    response = graph_client.post(
        "/api/internal/graph/rebuild", headers=_auth_headers(graph_client)
    )
    assert response.status_code == 200


@pytest.fixture
def zhangc3_id(db_session) -> int:
    return db_session.scalar(select(Customer.id).where(Customer.username == "zhangc3"))


def test_customer_graph_requires_auth(graph_client):
    response = graph_client.get("/api/internal/graph/customers/1")
    assert response.status_code == 401


def test_customer_graph_rejects_non_positive_customer_id(graph_client):
    response = graph_client.get(
        "/api/internal/graph/customers/0", headers=_auth_headers(graph_client)
    )
    assert response.status_code == 400


def test_customer_graph_default_two_hops(graph_client, zhangc3_id):
    response = graph_client.get(
        f"/api/internal/graph/customers/{zhangc3_id}", headers=_auth_headers(graph_client)
    )
    assert response.status_code == 200
    data = response.json()["data"]

    node_types = {node["type"] for node in data["nodes"]}
    assert node_types == {"customer", "product", "industry"}

    edge_types = {edge["type"] for edge in data["edges"]}
    assert edge_types == {"HOLDS", "BELONGS_TO_INDUSTRY"}

    product_nodes = [node for node in data["nodes"] if node["type"] == "product"]
    assert {node["id"] for node in product_nodes} == {"product:F000003"}
    assert product_nodes[0]["attrs"]["product_name"] == "天璇混合基金"

    customer_nodes = [node for node in data["nodes"] if node["type"] == "customer"]
    assert customer_nodes[0]["id"] == f"customer:{zhangc3_id}"


def test_customer_graph_marks_industry_over_concentration_threshold(graph_client, zhangc3_id):
    response = graph_client.get(
        f"/api/internal/graph/customers/{zhangc3_id}", headers=_auth_headers(graph_client)
    )
    data = response.json()["data"]

    industries = {node["label"]: node for node in data["nodes"] if node["type"] == "industry"}
    assert industries["大盘蓝筹"]["marked"] is True  # 2/3 敞口，超过 40% 阈值
    assert industries["利率债"]["marked"] is False  # 1/3 敞口，未超过阈值


def test_customer_graph_expand_fund_manager_adds_third_hop(graph_client, zhangc3_id):
    without_expand = graph_client.get(
        f"/api/internal/graph/customers/{zhangc3_id}", headers=_auth_headers(graph_client)
    ).json()["data"]
    assert "fund_manager" not in {node["type"] for node in without_expand["nodes"]}

    expanded = graph_client.get(
        f"/api/internal/graph/customers/{zhangc3_id}?expand=fund_manager",
        headers=_auth_headers(graph_client),
    ).json()["data"]

    fund_manager_nodes = [node for node in expanded["nodes"] if node["type"] == "fund_manager"]
    assert len(fund_manager_nodes) >= 1
    assert "MANAGED_BY" in {edge["type"] for edge in expanded["edges"]}


def test_customer_graph_unknown_customer_returns_empty(graph_client):
    response = graph_client.get(
        "/api/internal/graph/customers/999999998", headers=_auth_headers(graph_client)
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["nodes"] == []
    assert data["edges"] == []


def test_customer_graph_reports_synced_at_consistent_with_stats(graph_client, zhangc3_id):
    stats = graph_client.get(
        "/api/internal/graph/stats", headers=_auth_headers(graph_client)
    ).json()["data"]

    graph = graph_client.get(
        f"/api/internal/graph/customers/{zhangc3_id}", headers=_auth_headers(graph_client)
    ).json()["data"]

    assert graph["synced_at"] == stats["synced_at"]
