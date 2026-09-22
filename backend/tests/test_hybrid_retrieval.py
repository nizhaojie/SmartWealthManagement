"""混合检索（向量臂 ∥ BM25 关键词臂 → RRF）与分臂兜底判定（issue 02）。

两个 seam：

- **纯函数**：RRF 融合与分臂判定，不需要任何基础设施；
- **后端 HTTP 层**：字面查询能命中对应问答、S1 / S2 / S5 / S8 的作答与兜底、
  内部检索接口与聊天检索同序。

`retrieval_keyword_score_threshold` 的量纲在本次改动里从「命中字词占比」变成 BM25
分（默认值已由 issue 04 校准为 13.0），但 S1 / S2 的安全边界对「阈值取多少」敏感，
而校准值量的是另一份语料上的分布，因此这里的用例**一律注入**该阈值、自己掌握分界。
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Literal

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session as OrmSession

import app.agent.graph as agent_graph
from app.agent.config import CUSTOMER_SERVICE_CONFIG
from app.agent.graph import build_retrieval_evidence, has_retrieval_evidence
from app.db.models import AgentDebugTrace, DegradationTrace
from app.knowledge.hybrid import rrf_fuse, tokenize
from app.knowledge.service import ChunkResult
from app.knowledge_graph.graphrag import GraphAugmentation, GraphPassage
from app.llm.provider import GroundedAnswer
from app.main import app
from app.settings import get_settings

CUSTOMER_USERNAME = "wangc1"
EMPLOYEE_USERNAME = "advisor1"
SEEDED_PASSWORD = "Test@1234"
UNUSED_GRAPH_NAMESPACE = "wealth_test_hybrid_retrieval_unused"

# 注入的关键词臂阈值：正例与负例的分界由用例自己掌握，不等校准结果。
KEYWORD_THRESHOLD = 1.0

# 一组「字面明确」的问答对：向量对短实体、代码与数字串的区分力不如字面匹配，
# 关键词臂存在的理由就是这几类查询（ADR-0022）。
LITERAL_FAQ = (
    "T+1 到账\t本产品赎回资金 T+1 个交易日到账，遇非交易日顺延。\n"
    "七日年化收益率\t七日年化收益率按最近七个自然日的收益折算成年化收益率。\n"
    "客服电话\t客服热线 400-888-9558，工作日 9:00 至 18:00。\n"
)
TIMEOUT_FAQ_TEXT = "本产品的管理费率为百分之一点二每年，最短持有期为九十天。"
TIMEOUT_FAQ_QUESTION = "本产品的管理费率是多少"


def _override_settings(**overrides):
    base = get_settings()
    settings = base.model_copy(
        update={
            "milvus_collection": base.test_milvus_collection,
            "embedding_api_key": "",
            "llm_api_key": "",
            # 独立、从不重建的命名空间：让 GraphRAG 稳定走「实体未命中」，
            # 用例只观察召回臂与分臂判定。
            "neo4j_graph_namespace": UNUSED_GRAPH_NAMESPACE,
            "retrieval_keyword_score_threshold": KEYWORD_THRESHOLD,
            **overrides,
        }
    )
    app.dependency_overrides[get_settings] = lambda: settings
    return settings


def _clear_degradation_traces() -> None:
    engine = create_engine(get_settings().test_database_url)
    try:
        with OrmSession(engine) as session:
            session.execute(delete(DegradationTrace))
            session.commit()
    finally:
        engine.dispose()


@pytest.fixture
def hybrid_client(auth_client: TestClient) -> Iterator[TestClient]:
    _override_settings()
    _clear_degradation_traces()
    try:
        yield auth_client
    finally:
        _clear_degradation_traces()
        app.dependency_overrides.pop(get_settings, None)


def _customer_login(client: TestClient) -> tuple[str, str]:
    response = client.post(
        "/api/customer/auth/login",
        json={"username": CUSTOMER_USERNAME, "password": SEEDED_PASSWORD},
    )
    access_token = response.json()["data"]["access_token"]
    session_id = pyjwt.decode(access_token, options={"verify_signature": False})["sid"]
    return access_token, session_id


def _internal_headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/internal/auth/login",
        json={"username": EMPLOYEE_USERNAME, "password": SEEDED_PASSWORD},
    )
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


def _chat(client: TestClient, token: str, message: str):
    return client.post(
        "/api/customer/chat/messages",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": message},
    )


def _search(client: TestClient, *, query: str, top_k: int = 5):
    return client.post(
        "/api/internal/knowledge/search",
        headers=_internal_headers(client),
        json={"query": query, "top_k": top_k},
    )


def _upload(client: TestClient, *, filename: str, content: bytes, knowledge_type: str = "FAQ"):
    return client.post(
        "/api/internal/knowledge/documents",
        headers=_internal_headers(client),
        files={"file": (filename, content, "text/plain")},
        data={"knowledge_type": knowledge_type},
    )


def _delete(client: TestClient, knowledge_id: int):
    return client.delete(
        f"/api/internal/knowledge/documents/{knowledge_id}",
        headers=_internal_headers(client),
    )


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


def _degradation_rows() -> list[DegradationTrace]:
    engine = create_engine(get_settings().test_database_url)
    try:
        with OrmSession(engine) as session:
            return list(
                session.scalars(select(DegradationTrace).order_by(DegradationTrace.id))
            )
    finally:
        engine.dispose()


def _chunk(
    knowledge_id: int,
    *,
    source: Literal["vector", "keyword", "graph", "hybrid"],
    evidence_score: float,
    score: float = 1.0,
) -> ChunkResult:
    return ChunkResult(
        knowledge_id=knowledge_id,
        knowledge_type="FAQ",
        chunk_index=0,
        heading_path=[],
        content=f"检索片段 {knowledge_id}",
        score=score,
        title="测试文档",
        source_file="stub.txt",
        evidence_score=evidence_score,
        source=source,
    )


def _fail_generation(*_args, **_kwargs):
    raise AssertionError("没有依据时不应发起生成")


def _stub_generation(question, history, chunks, settings) -> GroundedAnswer:
    return GroundedAnswer(text=f"{chunks[0].content}[1]", cited_chunk_numbers=[1])


# --- 纯函数：RRF ---


def test_rrf_merges_a_chunk_hit_by_both_arms_into_one_hybrid_candidate():
    vector_arm = [_chunk(1, source="vector", evidence_score=0.42)]
    keyword_arm = [
        _chunk(1, source="keyword", evidence_score=8.0),
        _chunk(2, source="keyword", evidence_score=6.0),
    ]

    fused = rrf_fuse([vector_arm, keyword_arm], rrf_k=60, top_k=10)

    assert [chunk.knowledge_id for chunk in fused] == [1, 2]
    merged = fused[0]
    assert merged.source == "hybrid", "两路都命中的块是一条候选，来源标 hybrid"
    assert merged.evidence_score == 8.0, "证据分取两路中的较大值"


def test_rrf_ranks_a_candidate_hit_by_both_arms_above_single_arm_candidates():
    vector_arm = [_chunk(1, source="vector", evidence_score=0.9), _chunk(2, source="vector", evidence_score=0.8)]
    keyword_arm = [_chunk(2, source="keyword", evidence_score=9.0)]

    fused = rrf_fuse([vector_arm, keyword_arm], rrf_k=60, top_k=10)

    assert fused[0].knowledge_id == 2


def test_rrf_score_is_a_normalized_monotonically_decreasing_value():
    fused = rrf_fuse(
        [[_chunk(1, source="vector", evidence_score=0.9), _chunk(2, source="vector", evidence_score=0.8)]],
        rrf_k=60,
        top_k=10,
    )

    scores = [chunk.score for chunk in fused]
    assert scores[0] == 1.0, "本次候选的最高 RRF 记 1.0"
    assert scores == sorted(scores, reverse=True)
    assert all(0.0 < score <= 1.0 for score in scores)


def test_rrf_returns_nothing_when_every_arm_is_empty():
    assert rrf_fuse([[], []], rrf_k=60, top_k=10) == []


def test_tokenize_keeps_alnum_tokens_and_drops_pure_punctuation():
    tokens = tokenize("T+1 到账，七日年化收益率。")

    # 查询侧与文档侧共用同一个分词器：切分是否「符合语感」不重要，重要的是两侧一致
    # （jieba 把「到账」切成「到 / 账」也没关系，文档侧同样这么切）。
    assert "T" in tokens and "1" in tokens
    assert "年化" in tokens and "收益率" in tokens
    assert all(any(char.isalnum() for char in token) for token in tokens)


# --- 纯函数：分臂证据与判定 ---


def test_build_retrieval_evidence_keeps_each_arms_own_scale():
    chunks = [
        _chunk(1, source="vector", evidence_score=0.42),
        _chunk(2, source="keyword", evidence_score=8.0),
    ]

    assert build_retrieval_evidence(chunks) == {
        "vector": 0.42,
        "keyword": 8.0,
        "graph": 0.0,
    }


def test_has_retrieval_evidence_accepts_any_single_arm():
    thresholds = {"vector_threshold": 0.55, "keyword_threshold": KEYWORD_THRESHOLD}

    # S1：向量余弦未达标、关键词 BM25 达标。
    assert has_retrieval_evidence({"vector": 0.42, "keyword": 4.0, "graph": 0.0}, **thresholds)
    # S8：两臂均未达标，仅图谱有段落。
    assert has_retrieval_evidence({"vector": 0.42, "keyword": 0.5, "graph": 1.0}, **thresholds)
    # S2：两臂均未达标、也没有图谱段落。
    assert not has_retrieval_evidence(
        {"vector": 0.42, "keyword": 0.5, "graph": 0.0}, **thresholds
    )


# --- HTTP 层：字面查询 ---


@pytest.mark.parametrize(
    ("query", "marker"),
    [
        ("T+1 到账", "T+1"),
        ("七日年化收益率怎么算", "七日年化收益率"),
        ("客服电话是多少", "400-888-9558"),
    ],
)
def test_literal_query_hits_the_matching_faq_pair(hybrid_client, query, marker):
    upload = _upload(
        hybrid_client,
        filename="test_hybrid_literal.txt",
        content=LITERAL_FAQ.encode("utf-8"),
    )
    knowledge_id = upload.json()["data"]["knowledge_id"]

    try:
        response = _search(hybrid_client, query=query, top_k=20)
        hits = response.json()["data"]["hits"]
        assert any(
            hit["knowledge_id"] == knowledge_id and marker in hit["content"]
            for hit in hits
        ), f"字面明确的查询（{marker}）必须命中对应问答"
    finally:
        _delete(hybrid_client, knowledge_id)


# --- HTTP 层：分臂判定（S1 / S2 / S8） ---


def test_both_arms_below_their_thresholds_fall_back_even_with_an_rrf_leader(
    hybrid_client, monkeypatch
):
    """S2：RRF 只排序，不改变「有没有依据」——两臂都没达标就兜底。"""
    monkeypatch.setattr(
        agent_graph,
        "search_chunks",
        lambda *a, **k: [
            _chunk(1, source="vector", evidence_score=0.42, score=1.0),
            _chunk(2, source="keyword", evidence_score=0.5, score=0.9),
        ],
    )
    monkeypatch.setattr(agent_graph, "generate_grounded_answer", _fail_generation)

    token, _ = _customer_login(hybrid_client)
    response = _chat(hybrid_client, token, TIMEOUT_FAQ_QUESTION)

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["citations"] == []
    assert "95588" in data["answer"]


def test_keyword_arm_above_its_threshold_is_enough_to_generate(hybrid_client, monkeypatch):
    """S1：向量余弦 0.42 未达标、BM25 达标 → 进入生成。"""
    monkeypatch.setattr(
        agent_graph,
        "search_chunks",
        lambda *a, **k: [
            _chunk(1, source="vector", evidence_score=0.42, score=0.8),
            _chunk(2, source="keyword", evidence_score=KEYWORD_THRESHOLD + 3, score=0.9),
        ],
    )
    monkeypatch.setattr(agent_graph, "generate_grounded_answer", _stub_generation)

    token, _ = _customer_login(hybrid_client)
    response = _chat(hybrid_client, token, TIMEOUT_FAQ_QUESTION)

    assert response.status_code == 200
    assert response.json()["data"]["citations"], "关键词臂达标即可作答"


def test_graph_passages_alone_are_enough_to_generate(hybrid_client, monkeypatch):
    """S8：两臂均未达标、仅图谱有段落 → 进入生成（图谱是增强不是依赖的另一面）。"""
    monkeypatch.setattr(
        agent_graph,
        "search_chunks",
        lambda *a, **k: [_chunk(1, source="vector", evidence_score=0.42, score=0.7)],
    )
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
            ]
        ),
    )
    monkeypatch.setattr(agent_graph, "generate_grounded_answer", _stub_generation)

    token, _ = _customer_login(hybrid_client)
    response = _chat(hybrid_client, token, TIMEOUT_FAQ_QUESTION)

    assert response.status_code == 200
    assert response.json()["data"]["citations"], "仅图谱命中仍应作答"


# --- HTTP 层：向量臂超时（S5） ---


def test_vector_arm_timeout_answers_from_the_keyword_arm_only(hybrid_client, monkeypatch):
    """S5：向量臂超时只是少了一路召回，仍只用关键词臂作答并留一条降级痕迹。"""
    _override_settings(vector_search_timeout_seconds=0.1)
    upload = _upload(
        hybrid_client,
        filename="test_hybrid_timeout.txt",
        content=TIMEOUT_FAQ_TEXT.encode("utf-8"),
    )
    knowledge_id = upload.json()["data"]["knowledge_id"]

    def _slow(*_args, **_kwargs):
        # 比阈值慢即可；线程池的软超时不等它收尾。
        time.sleep(0.4)
        return []

    monkeypatch.setattr("app.knowledge.service._vector_search_hits", _slow)

    try:
        token, session_id = _customer_login(hybrid_client)
        response = _chat(hybrid_client, token, TIMEOUT_FAQ_QUESTION)

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["citations"], "关键词臂达标时应照常作答"
        assert data["degraded"] is True

        snippets = _debug_snippets(session_id)
        assert snippets, "关键词臂应给出候选"
        assert {snippet["source"] for snippet in snippets} == {"keyword"}
        assert any(snippet["knowledge_id"] == knowledge_id for snippet in snippets)
    finally:
        _delete(hybrid_client, knowledge_id)

    rows = _degradation_rows()
    assert [(row.dependency, row.reason) for row in rows] == [
        ("vector_store", "timeout")
    ]


# --- HTTP 层：内部检索与聊天同一条流水线 ---


def test_internal_search_returns_the_same_order_as_the_chat_pipeline(hybrid_client):
    upload = _upload(
        hybrid_client,
        filename="test_hybrid_consistency.txt",
        content=LITERAL_FAQ.encode("utf-8"),
    )
    knowledge_id = upload.json()["data"]["knowledge_id"]

    try:
        query = "T+1 到账"
        token, session_id = _customer_login(hybrid_client)
        assert _chat(hybrid_client, token, query).status_code == 200

        # 聊天检索最终送进模型的条数与内部检索接口要的条数一致（重排后的最终条数，
        # 由 AgentConfig.retrieval_top_k 决定），两边才能比序。
        internal_hits = _search(
            hybrid_client, query=query, top_k=CUSTOMER_SERVICE_CONFIG.retrieval_top_k
        ).json()["data"]["hits"]
        snippets = _debug_snippets(session_id)

        assert internal_hits, "内部检索接口应有结果"
        assert [
            (hit["knowledge_id"], hit["chunk_index"]) for hit in internal_hits
        ] == [
            (snippet["knowledge_id"], snippet["chunk_index"]) for snippet in snippets
        ], "内部检索接口与聊天检索必须是同一条流水线、同一个顺序"
    finally:
        _delete(hybrid_client, knowledge_id)
