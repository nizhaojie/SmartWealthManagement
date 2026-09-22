from collections.abc import Iterator
from uuid import uuid4

import jwt as pyjwt
import pytest
import redis as redis_lib
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session as OrmSession

import app.agent.graph as agent_graph
from app.agent import memory as agent_memory
from app.db.models import ConversationArchive
from app.knowledge.service import ChunkResult
from app.knowledge_graph.graphrag import GraphAugmentation, GraphPassage
from app.llm.provider import GroundedAnswer
from app.main import app
from app.settings import get_settings

CUSTOMER_USERNAME = "wangc1"
CUSTOMER_REAL_NAME = "王守成"
CUSTOMER_ID_NUMBER = "110101198803150218"
CUSTOMER_PHONE = "13800138001"
CUSTOMER_BANK_CARD = "6222021234567890"
EMPLOYEE_USERNAME = "advisor1"
SEEDED_PASSWORD = "Test@1234"


@pytest.fixture
def chat_client(auth_client: TestClient) -> Iterator[TestClient]:
    base_settings = get_settings()
    test_settings = base_settings.model_copy(
        update={
            "milvus_collection": base_settings.test_milvus_collection,
            "embedding_api_key": "",
            "llm_api_key": "",
            # 独立、从不重建的命名空间：这些测试断言的是向量检索路径本身，
            # 不需要图谱数据参与——用一个保证为空的命名空间，让 GraphRAG 融合
            # 稳定走「实体未命中」静默降级，不会因为别的测试模块重建过
            # test_neo4j_graph_namespace 而产生跨文件的结果耦合。
            "neo4j_graph_namespace": "wealth_test_customer_service_agent_unused",
            # 关键词臂阈值在这里显式注入：它的量纲已从「命中字词占比」变成 BM25 分，
            # 默认值要等 golden 集校准（issue 04）写回，断言不能依赖默认值。
            # 取值只要求「分得开」：无关问题共享「系统」这类高频词时 BM25 约 4 分，
            # 而逐字命中一块约 40 分（见 test_unrelated_question... 与
            # test_question_matching_uploaded_document...）。
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
    access_token = response.json()["data"]["access_token"]
    session_id = pyjwt.decode(access_token, options={"verify_signature": False})["sid"]
    return access_token, session_id


def _internal_token(client: TestClient) -> str:
    response = client.post(
        "/api/internal/auth/login",
        json={"username": EMPLOYEE_USERNAME, "password": SEEDED_PASSWORD},
    )
    return response.json()["data"]["access_token"]


def _upload(client: TestClient, *, filename: str, content: bytes, knowledge_type: str = "FAQ"):
    return client.post(
        "/api/internal/knowledge/documents",
        headers={"Authorization": f"Bearer {_internal_token(client)}"},
        files={"file": (filename, content, "text/plain")},
        data={"knowledge_type": knowledge_type},
    )


def _delete(client: TestClient, knowledge_id: int):
    return client.delete(
        f"/api/internal/knowledge/documents/{knowledge_id}",
        headers={"Authorization": f"Bearer {_internal_token(client)}"},
    )


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


def _memory_length(session_id: str) -> int:
    client = redis_lib.Redis.from_url(get_settings().test_redis_url, decode_responses=True)
    try:
        return client.llen(f"agent:memory:{session_id}")
    finally:
        client.close()


def test_unrelated_question_returns_fallback_without_llm_call(chat_client, monkeypatch):
    def _fail(*args, **kwargs):
        raise AssertionError("生成回答不应在检索兜底路径上被调用")

    monkeypatch.setattr(agent_graph, "generate_grounded_answer", _fail)

    token, _ = _customer_login(chat_client)
    response = _chat(chat_client, token, "阿尔法半人马座恒星系统的行星编号列表是什么")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["citations"] == []
    assert "人工客服" in data["answer"] or "95588" in data["answer"]


def test_vector_hit_below_the_calibrated_threshold_falls_back(chat_client, monkeypatch):
    """阈值按向量臂的量纲校准：0.45 是真实 embedding 对无关文本的常见水平，必须兜底。

    这条用例把「RETRIEVAL_SCORE_THRESHOLD 已从 0.35 上调」钉住——退回旧值就失效。
    兜底判定读的是分臂证据（`evidence_score`），不是融合后的 `score`；这里两路都
    没有达标，因此即便这块排在候选第一位也不作答。
    """
    noisy = ChunkResult(
        knowledge_id=5555,
        knowledge_type="FAQ",
        chunk_index=0,
        heading_path=[],
        content="与本问题无关的检索片段。",
        score=0.45,
        title="无关文档",
        source_file="noise.txt",
        evidence_score=0.45,
    )
    monkeypatch.setattr(agent_graph, "search_chunks", lambda *a, **k: [noisy])

    def _fail(*args, **kwargs):
        raise AssertionError("证据分低于阈值不应发起生成")

    monkeypatch.setattr(agent_graph, "generate_grounded_answer", _fail)

    token, _ = _customer_login(chat_client)
    response = _chat(chat_client, token, "阿尔法半人马座恒星系统的行星编号列表是什么")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["citations"] == []
    assert "95588" in data["answer"]


def test_graph_fusion_does_not_scale_a_vector_hit_below_the_threshold(
    chat_client, monkeypatch
):
    """图谱参与融合只改变排序：向量命中分不被 vector_weight 打折，仍按原始相似度过阈值。

    融合后 chunks[0].score 是 0.6 * 0.9 = 0.54，低于阈值 0.55；兜底判定用的是融合前的
    证据分（向量 0.9 与图谱 1.0 取大），因此仍应生成。没有这次解耦，图谱一命中就会把
    向量命中的回答误判成「检索不到依据」。
    """
    hit = ChunkResult(
        knowledge_id=6666,
        knowledge_type="FAQ",
        chunk_index=0,
        heading_path=[],
        content="产品风险等级与客户风险承受等级是两套独立的刻度。",
        score=0.9,
        title="适当性匹配",
        source_file="suitability.txt",
        evidence_score=0.9,
    )
    monkeypatch.setattr(agent_graph, "search_chunks", lambda *a, **k: [hit])
    monkeypatch.setattr(
        agent_graph,
        "augment_with_graph",
        lambda *a, **k: GraphAugmentation(
            passages=[
                GraphPassage(
                    content="王守成持有产品「天枢货币基金」（货币基金，风险等级R1）。",
                    score=1.0,
                    entity_type="customer",
                    entity_value="王守成",
                    tool="customer_holdings",
                )
            ],
        ),
    )
    monkeypatch.setattr(
        agent_graph,
        "generate_grounded_answer",
        lambda question, history, chunks, settings: GroundedAnswer(
            text=f"{chunks[0].content}[1]", cited_chunk_numbers=[1]
        ),
    )

    token, _ = _customer_login(chat_client)
    response = _chat(chat_client, token, "客户能否申购超出自己风险承受等级的产品？")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["citations"], "向量命中不因图谱参与被权重打折，仍应生成带引用的回答"


def test_question_matching_uploaded_document_returns_structured_citations(chat_client):
    chunk_text = "本产品的管理费率为百分之一点二每年，最短持有期为九十天。"
    upload_response = _upload(
        chat_client, filename="test_agent_citation.txt", content=chunk_text.encode("utf-8"),
        knowledge_type="产品",
    )
    knowledge_id = upload_response.json()["data"]["knowledge_id"]

    try:
        token, _ = _customer_login(chat_client)
        response = _chat(chat_client, token, chunk_text)

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["citations"], "命中片段时应返回结构化引用"
        citation = data["citations"][0]
        assert citation["knowledge_id"] == knowledge_id
        assert citation["chunk_index"] == 0
        assert citation["source_file"] == "test_agent_citation.txt"
        assert chunk_text in data["answer"]
    finally:
        _delete(chat_client, knowledge_id)


def test_citation_referencing_nonexistent_chunk_is_dropped(chat_client, monkeypatch):
    only_chunk = ChunkResult(
        knowledge_id=4242,
        knowledge_type="FAQ",
        chunk_index=0,
        heading_path=[],
        content="客户经理更换流程需通过客服热线提交申请，三个工作日内完成。",
        score=0.99,
        title="客户经理更换须知",
        source_file="test_stub.txt",
        evidence_score=0.99,
    )
    monkeypatch.setattr(agent_graph, "search_chunks", lambda *args, **kwargs: [only_chunk])
    monkeypatch.setattr(
        agent_graph,
        "generate_grounded_answer",
        lambda question, history, chunks, settings: GroundedAnswer(
            text=f"{chunks[0].content}[1][99]", cited_chunk_numbers=[1, 99]
        ),
    )

    token, _ = _customer_login(chat_client)
    response = _chat(chat_client, token, "客户经理怎么更换")

    assert response.status_code == 200
    citations = response.json()["data"]["citations"]
    assert len(citations) == 1
    assert citations[0]["knowledge_id"] == only_chunk.knowledge_id
    assert citations[0]["chunk_index"] == only_chunk.chunk_index


def test_handoff_keyword_returns_fixed_script_without_retrieval(chat_client, monkeypatch):
    def _fail(*args, **kwargs):
        raise AssertionError("转人工不应触发检索")

    monkeypatch.setattr(agent_graph, "search_chunks", _fail)

    token, _ = _customer_login(chat_client)
    response = _chat(chat_client, token, "我要转人工投诉")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["intent"] == "转人工"
    assert data["citations"] == []
    assert data["answer"] == agent_graph.handoff_message(get_settings())


def test_chitchat_question_redirects_without_retrieval(chat_client, monkeypatch):
    def _fail(*args, **kwargs):
        raise AssertionError("闲聊不应触发检索")

    monkeypatch.setattr(agent_graph, "search_chunks", _fail)

    token, _ = _customer_login(chat_client)
    response = _chat(chat_client, token, "你好呀，今天天气不错")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["intent"] == "闲聊"
    assert data["citations"] == []
    assert data["answer"] != agent_graph.fallback_message(get_settings())
    assert data["answer"] != agent_graph.handoff_message(get_settings())


def test_multi_turn_history_is_kept_and_reset_on_relogin(chat_client):
    token, session_id = _customer_login(chat_client)

    _chat(chat_client, token, "你好呀")
    _chat(chat_client, token, "再问一句你好")

    assert _memory_length(session_id) == 4

    new_token, new_session_id = _customer_login(chat_client)
    assert new_session_id != session_id
    assert _memory_length(new_session_id) == 0

    _chat(chat_client, new_token, "你好呀")
    assert _memory_length(new_session_id) == 2
    assert _memory_length(session_id) == 4


def test_conversation_archive_masks_pii_before_storage(chat_client):
    token, session_id = _customer_login(chat_client)
    message = (
        f"你好，我是{CUSTOMER_REAL_NAME}，身份证号{CUSTOMER_ID_NUMBER}，"
        f"手机号{CUSTOMER_PHONE}，银行卡号{CUSTOMER_BANK_CARD}，在吗"
    )

    response = _chat(chat_client, token, message)
    assert response.status_code == 200

    rows = _archive_rows(session_id)
    assert len(rows) == 2
    user_row = next(row for row in rows if row.role == "user")
    assistant_row = next(row for row in rows if row.role == "assistant")

    assert CUSTOMER_REAL_NAME not in user_row.content
    assert CUSTOMER_ID_NUMBER not in user_row.content
    assert CUSTOMER_PHONE not in user_row.content
    assert CUSTOMER_BANK_CARD not in user_row.content
    assert "王**" in user_row.content
    assert "110101********0218" in user_row.content
    assert "138****8001" in user_row.content
    assert "************7890" in user_row.content

    assert assistant_row.content_classification == "事实性内容"
    assert assistant_row.citations in (None, [])


def test_tool_calls_are_archived_with_the_assistant_turn(chat_client):
    token, session_id = _customer_login(chat_client)

    response = _chat(chat_client, token, "阿尔法半人马座恒星系统的行星编号列表是什么")
    assert response.status_code == 200

    rows = _archive_rows(session_id)
    assistant_row = next(row for row in rows if row.role == "assistant")
    tools = {call["tool"] for call in (assistant_row.tool_calls or [])}
    assert {"knowledge_search", "graphrag_fusion"} <= tools


def test_memory_truncates_oldest_message_once_token_budget_exceeded():
    settings = get_settings().model_copy(update={"chat_memory_token_budget": 5})
    cache = redis_lib.Redis.from_url(get_settings().test_redis_url, decode_responses=True)
    session_id = f"test-memory-budget-{uuid4()}"

    try:
        agent_memory.append_turn(cache, session_id, role="user", content="你好呀", settings=settings)
        agent_memory.append_turn(cache, session_id, role="assistant", content="早", settings=settings)
        agent_memory.append_turn(cache, session_id, role="user", content="在吗", settings=settings)

        history = agent_memory.get_history(cache, session_id)
        assert [item["content"] for item in history] == ["早", "在吗"]
    finally:
        cache.delete(f"agent:memory:{session_id}")
        cache.close()
