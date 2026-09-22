"""Seam 1：GraphRAG 融合接入智能客服对话链路（ticket 03）。

`test_customer_service_agent.py` 里的 chat_client 特意把命名空间指向
一个从不重建的空间，让那批测试保持在「纯向量检索」的既有世界里
（见该文件 chat_client 的注释）。这里反过来：用真实、重建过的图谱，
验证融合结果真的能改变对话接口拿到的上下文与留痕。
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from neo4j import GraphDatabase
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session as OrmSession

from app.db.models import AgentDebugTrace, ConversationArchive
from app.db.seed import seed
from app.knowledge_graph import sync
from app.main import app
from app.settings import get_settings

CUSTOMER_USERNAME = "wangc1"
SEEDED_PASSWORD = "Test@1234"


@pytest.fixture(scope="module")
def _graph_rebuilt() -> None:
    settings = get_settings()
    seed(settings.test_database_url)
    engine = create_engine(settings.test_database_url)
    driver = GraphDatabase.driver(
        settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password)
    )
    try:
        with OrmSession(engine) as session:
            sync.rebuild_graph(session, driver, namespace=settings.test_neo4j_graph_namespace)
    finally:
        driver.close()
        engine.dispose()


@pytest.fixture
def chat_client(auth_client: TestClient, _graph_rebuilt: None) -> Iterator[TestClient]:
    base_settings = get_settings()
    test_settings = base_settings.model_copy(
        update={
            "milvus_collection": base_settings.test_milvus_collection,
            "embedding_api_key": "",
            "llm_api_key": "",
            "neo4j_graph_namespace": base_settings.test_neo4j_graph_namespace,
            # 关键词臂阈值在这里显式注入：「实体未命中 / 图谱不可用时应兜底」这两条
            # 断言要的是用例自己掌握的分界，不依赖 issue 04 校准出的默认值（它随语料漂移）。
            "retrieval_keyword_score_threshold": 10.0,
        }
    )
    app.dependency_overrides[get_settings] = lambda: test_settings
    try:
        yield auth_client
    finally:
        app.dependency_overrides.pop(get_settings, None)


def _customer_login(client: TestClient) -> tuple[str, str]:
    response = client.post(
        "/api/customer/auth/login",
        json={"username": CUSTOMER_USERNAME, "password": SEEDED_PASSWORD},
    )
    import jwt as pyjwt

    access_token = response.json()["data"]["access_token"]
    session_id = pyjwt.decode(access_token, options={"verify_signature": False})["sid"]
    return access_token, session_id


def _chat(client: TestClient, token: str, message: str):
    return client.post(
        "/api/customer/chat/messages",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": message},
    )


def _archive_rows(session_id: str) -> list[ConversationArchive]:
    engine = create_engine(get_settings().test_database_url)
    try:
        with OrmSession(engine) as session:
            return list(
                session.scalars(
                    select(ConversationArchive)
                    .where(ConversationArchive.session_id == session_id)
                    .order_by(ConversationArchive.id)
                )
            )
    finally:
        engine.dispose()


def _debug_snippets(session_id: str) -> list[dict]:
    engine = create_engine(get_settings().test_database_url)
    try:
        with OrmSession(engine) as session:
            row = session.scalar(
                select(AgentDebugTrace)
                .where(AgentDebugTrace.session_id == session_id)
                .order_by(AgentDebugTrace.id.desc())
            )
    finally:
        engine.dispose()
    assert row is not None
    return list(row.retrieval_snippets or [])


def test_graph_entity_hit_produces_grounded_answer_and_graph_citation(chat_client):
    """图谱命中要真的改变送进模型的上下文与留痕。

    注：混合检索之后，相似度候选的 `score` 是**归一化 RRF**（最高记 1.0），乘上
    `graphrag_vector_weight`（0.6）后恒高于图谱段落的 `graph_weight * 1.0`（0.4）
    ——图谱段落因此恒定排在相似度候选之后（「恒定附加」）。它仍在上下文里、仍可被
    引用，但不再保证落在前三个角标内，所以这里断言的是「它在上下文与留痕里」，
    而不是具体某个角标。
    """
    token, session_id = _customer_login(chat_client)

    response = _chat(chat_client, token, "天璇混合基金主要投在哪些行业")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["citations"], "图谱命中应当产出可供展示的引用"

    snippets = _debug_snippets(session_id)
    assert any(snippet["source"] == "graph" for snippet in snippets), "图谱段落应进入上下文"
    assert any(snippet["title"] == "知识图谱" for snippet in snippets)

    rows = _archive_rows(session_id)
    assistant_row = next(row for row in rows if row.role == "assistant")
    fusion_call = next(call for call in assistant_row.tool_calls if call["tool"] == "graphrag_fusion")
    assert fusion_call["output"]["degraded"] is False
    assert {"type": "product", "value": "天璇混合基金"} in fusion_call["output"]["matched_entities"]
    assert fusion_call["output"]["graph_hit_count"] > 0
    assert fusion_call["output"]["retrieval_evidence"]["graph"] == 1.0


def test_another_customers_name_does_not_bring_their_portfolio_into_the_context(chat_client):
    """客户可见视图里只有本人的持仓：问句里出现别人的姓名，也不能把别人的持仓拉进上下文。

    与 `test_knowledge_graph_graphrag.py` 的 `only_customer_id` 用例上下同源：
    客服链路把登录客户标识传进图谱增强，别人的姓名因此解析不出实体，图谱按
    「实体未命中」静默降级——客户看到的只是知识库回答或兜底话术。
    """
    token, session_id = _customer_login(chat_client)

    response = _chat(chat_client, token, "赵启明的持仓集中在哪些行业")

    assert response.status_code == 200
    snippets = _debug_snippets(session_id)
    assert not any("赵启明" in snippet["content"] for snippet in snippets)
    rows = _archive_rows(session_id)
    assistant_row = next(row for row in rows if row.role == "assistant")
    fusion_call = next(call for call in assistant_row.tool_calls if call["tool"] == "graphrag_fusion")
    assert fusion_call["output"]["matched_entities"] == []
    assert fusion_call["output"]["degradation_reason"] == "entity_not_matched"


def test_the_customers_own_name_still_reaches_the_graph(chat_client):
    """收紧到本人不等于关掉图谱：登录客户自己的姓名照常命中。"""
    token, session_id = _customer_login(chat_client)

    response = _chat(chat_client, token, "王守成的持仓集中在哪些行业")

    assert response.status_code == 200
    snippets = _debug_snippets(session_id)
    assert any("王守成" in snippet["content"] for snippet in snippets), (
        "登录客户本人的持仓应当仍可由图谱命中"
    )


def test_no_entity_match_degrades_silently_and_records_reason(chat_client):
    token, session_id = _customer_login(chat_client)

    response = _chat(chat_client, token, "阿尔法半人马座恒星系统的行星编号列表是什么")

    assert response.status_code == 200
    data = response.json()["data"]
    assert "人工客服" in data["answer"] or "95588" in data["answer"]

    rows = _archive_rows(session_id)
    assistant_row = next(row for row in rows if row.role == "assistant")
    fusion_call = next(call for call in assistant_row.tool_calls if call["tool"] == "graphrag_fusion")
    assert fusion_call["output"]["degraded"] is True
    assert fusion_call["output"]["degradation_reason"] == "entity_not_matched"


def test_neo4j_unavailable_degrades_silently_and_answer_still_returns(chat_client):
    from app.neo4j_client import get_neo4j

    base_settings = get_settings()
    # max_transaction_retry_time 调小、query 超时调大：确保这里量到的是驱动最终
    # 抛出的 ServiceUnavailable，而不是被我们自己的软超时先一步截胡
    # （同样的取舍见 test_knowledge_graph_graphrag.py 对应的用例）。
    unreachable_driver = GraphDatabase.driver(
        "bolt://127.0.0.1:1",
        auth=("neo4j", "wrong"),
        connection_timeout=1.0,
        max_transaction_retry_time=0.5,
    )
    app.dependency_overrides[get_neo4j] = lambda: unreachable_driver
    app.dependency_overrides[get_settings] = lambda: base_settings.model_copy(
        update={
            "milvus_collection": base_settings.test_milvus_collection,
            "embedding_api_key": "",
            "llm_api_key": "",
            "neo4j_graph_namespace": base_settings.test_neo4j_graph_namespace,
            "graphrag_query_timeout_seconds": 10.0,
        }
    )
    try:
        token, session_id = _customer_login(chat_client)
        response = _chat(chat_client, token, "天璇混合基金主要投在哪些行业")
    finally:
        app.dependency_overrides.pop(get_neo4j, None)
        unreachable_driver.close()

    assert response.status_code == 200
    data = response.json()["data"]
    assert "人工客服" in data["answer"] or "95588" in data["answer"]

    rows = _archive_rows(session_id)
    assistant_row = next(row for row in rows if row.role == "assistant")
    fusion_call = next(call for call in assistant_row.tool_calls if call["tool"] == "graphrag_fusion")
    assert fusion_call["output"]["degraded"] is True
    assert fusion_call["output"]["degradation_reason"] == "neo4j_unavailable"
