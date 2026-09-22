"""候选集的 LLM 重排：保底占位（Q18）、恒等保序与降级（issue 03）。

两个 seam：

- **纯函数**：重排输出的解析与「达标块保底占位」的组装，不需要任何基础设施；
- **后端 HTTP 层**：重排把达标块排到最后时它仍在送进模型的上下文里、重排超时退回
  RRF 序且回答照常产出、`fake` provider 下恒等保序且不发起任何 HTTP 请求。

`retrieval_keyword_score_threshold` 的量纲在 02 里变成了 BM25 分，默认值要等 issue 04
的校准脚本写回，因此这里的用例**一律注入**该阈值，不依赖默认值。
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Literal

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session as OrmSession

import app.agent.graph as agent_graph
import app.llm.provider as provider
from app.db.models import DegradationTrace
from app.knowledge.rerank import (
    assemble_context_with_guarantee,
    parse_ranking,
    rerank_chunks,
)
from app.knowledge.service import ChunkResult, RetrievedChunks, search_chunks
from app.llm.provider import GroundedAnswer
from app.main import app
from app.settings import Settings, get_settings

CUSTOMER_USERNAME = "wangc1"
EMPLOYEE_USERNAME = "advisor1"
SEEDED_PASSWORD = "Test@1234"
UNUSED_GRAPH_NAMESPACE = "wealth_test_rerank_unused"

# 注入的两条阈值：用例自己掌握「哪块达标」，不等 issue 04 的校准结果。
VECTOR_THRESHOLD = 0.55
KEYWORD_THRESHOLD = 10.0

# 一条「字面明确」的问题：它触发的是真实检索流水线，而不是检索替身。
LITERAL_QUESTION = "T+1 到账"


def _override_settings(**overrides) -> Settings:
    base = get_settings()
    settings = base.model_copy(
        update={
            "milvus_collection": base.test_milvus_collection,
            "embedding_api_key": "",
            "llm_api_key": "",
            # 独立、从不重建的命名空间：让 GraphRAG 稳定走「实体未命中」，
            # 用例只观察重排这一段。
            "neo4j_graph_namespace": UNUSED_GRAPH_NAMESPACE,
            "retrieval_score_threshold": VECTOR_THRESHOLD,
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
def rerank_client(auth_client: TestClient) -> Iterator[TestClient]:
    _override_settings()
    _clear_degradation_traces()
    try:
        yield auth_client
    finally:
        _clear_degradation_traces()
        app.dependency_overrides.pop(get_settings, None)


@contextmanager
def _session() -> Iterator[OrmSession]:
    engine = create_engine(get_settings().test_database_url)
    try:
        with OrmSession(engine) as session:
            yield session
    finally:
        engine.dispose()


def _degradation_rows() -> list[DegradationTrace]:
    engine = create_engine(get_settings().test_database_url)
    try:
        with OrmSession(engine) as session:
            return list(
                session.scalars(select(DegradationTrace).order_by(DegradationTrace.id))
            )
    finally:
        engine.dispose()


def _customer_login(client: TestClient) -> tuple[str, str]:
    response = client.post(
        "/api/customer/auth/login",
        json={"username": CUSTOMER_USERNAME, "password": SEEDED_PASSWORD},
    )
    access_token = response.json()["data"]["access_token"]
    session_id = pyjwt.decode(access_token, options={"verify_signature": False})["sid"]
    return access_token, session_id


def _chat(client: TestClient, token: str, message: str):
    return client.post(
        "/api/customer/chat/messages",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": message},
    )


def _internal_headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/internal/auth/login",
        json={"username": EMPLOYEE_USERNAME, "password": SEEDED_PASSWORD},
    )
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


def _chunk(
    knowledge_id: int,
    *,
    source: Literal["vector", "keyword", "graph", "hybrid"] = "vector",
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


def _ranking_response(order: list[int]) -> str:
    """模型输出的替身：按给定序号从高到低打分（第一名的相关性最高）。"""
    return json.dumps(
        {
            "ranking": [
                {"index": index, "score": round(0.9 - position * 0.1, 2)}
                for position, index in enumerate(order)
            ]
        }
    )


# --- 纯函数：重排输出的解析 ---


def test_parse_ranking_reads_indices_and_clamps_scores():
    ranking = parse_ranking(
        '{"ranking": [{"index": 2, "score": 1.4}, {"index": 1, "score": 0.2}]}',
        candidate_count=2,
    )

    assert ranking == [(1, 1.0), (0, 0.2)], "相关度截断到 [0, 1]，下标从 0 起"


def test_parse_ranking_drops_out_of_range_duplicate_and_non_numeric_entries():
    ranking = parse_ranking(
        '{"ranking": [{"index": 0, "score": 0.9}, {"index": 3, "score": 0.9},'
        ' {"index": 1, "score": 0.9}, {"index": 1, "score": 0.1},'
        ' {"index": "二", "score": 0.9}, {"index": 2}]}',
        candidate_count=2,
    )

    # index 0 越界（序号从 1 起）、index 3 越界、index 1 重复（取先出现的 0.9）、
    # "二" 非数值、缺 score——都丢掉，只留一条。
    assert ranking == [(0, 0.9)], "越界 / 重复 / 非数值一律丢弃"


@pytest.mark.parametrize(
    "content",
    [
        "不是 JSON",
        '{"order": [1, 2]}',
        '{"ranking": "1,2"}',
        '{"ranking": []}',
        '{"ranking": [{"index": 99, "score": 0.9}]}',
    ],
)
def test_parse_ranking_rejects_unusable_output(content):
    with pytest.raises(ValueError):
        parse_ranking(content, candidate_count=2)


# --- 纯函数：达标块保底占位（Q18） ---


def _assemble_settings() -> Settings:
    return get_settings().model_copy(
        update={
            "retrieval_score_threshold": VECTOR_THRESHOLD,
            "retrieval_keyword_score_threshold": KEYWORD_THRESHOLD,
        }
    )


def test_assemble_final_keeps_a_qualified_chunk_ranked_outside_the_context():
    """重排把达标块排到 top-k 之外时，它仍然进上下文（Q18）。"""
    vector_chunks = [_chunk(index, evidence_score=0.42) for index in range(1, 6)]
    qualified = _chunk(99, source="keyword", evidence_score=30.0)
    ranked = [*vector_chunks, qualified]

    final = assemble_context_with_guarantee(
        ranked, settings=_assemble_settings(), top_k=5
    )

    assert len(final) == 5
    assert qualified.knowledge_id in [chunk.knowledge_id for chunk in final]
    assert final[-1].knowledge_id == 99, "顺序仍是重排序：达标块排在它原本的位置"
    assert 5 not in [chunk.knowledge_id for chunk in final], "被挤掉的是排名最末的未达标块"


def test_assemble_final_keeps_every_qualified_chunk_when_the_ranking_disagrees():
    """未达标的块排在达标块之前时它就在前面，但不挤掉达标块的名额。"""
    unqualified = [_chunk(index, evidence_score=0.42) for index in range(1, 7)]
    qualified = _chunk(99, source="keyword", evidence_score=30.0)
    ranked = [*unqualified, qualified]

    final = assemble_context_with_guarantee(
        ranked, settings=_assemble_settings(), top_k=2
    )

    assert [chunk.knowledge_id for chunk in final] == [1, 99]


def test_assemble_context_truncates_by_ranking_when_qualified_chunks_exceed_the_quota():
    qualified = [_chunk(index, source="keyword", evidence_score=30.0) for index in range(1, 4)]

    final = assemble_context_with_guarantee(
        qualified, settings=_assemble_settings(), top_k=2
    )

    assert [chunk.knowledge_id for chunk in final] == [1, 2]


def test_protective_threshold_for_a_hybrid_chunk_is_the_looser_of_the_two():
    """hybrid 块事后分不清分属于哪条臂，保底取两臂中较松的阈值（宁可多保一格）。"""
    settings = get_settings().model_copy(
        update={
            "retrieval_score_threshold": 0.9,
            "retrieval_keyword_score_threshold": 0.5,
        }
    )
    hybrid = _chunk(1, source="hybrid", evidence_score=0.6)

    assert assemble_context_with_guarantee([hybrid], settings=settings, top_k=1) == [hybrid]


# --- 纯函数：跳过与降级都恒等保序 ---


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"rerank_enabled": False}, "重排被关掉"),
        ({"llm_api_key": ""}, "fake provider"),
        ({"demo_replay": True, "llm_api_key": "test-key"}, "回放模式"),
    ],
)
def test_rerank_skips_without_any_model_call_and_keeps_the_rrf_order(
    monkeypatch, overrides, reason
):
    def _fail(*_args, **_kwargs):
        raise AssertionError(f"{reason}下不该发起重排调用")

    monkeypatch.setattr(provider, "_request_chat", _fail)
    settings = get_settings().model_copy(
        update={
            "llm_api_base": "http://llm.invalid/v1",
            "llm_api_key": "test-key",
            **overrides,
        }
    )
    candidates = RetrievedChunks(
        [
            _chunk(1, evidence_score=0.42, score=1.0),
            # 一条 hybrid 块（两路都命中，证据分取的是 BM25 那一侧的 30）：
            # 缺了它，「从融合结果反推证据集」这条错路会把 30 记进向量臂——
            # 余弦阈值是 0.55，BM25 的量纲冒充余弦会让向量臂凭空达标。
            _chunk(2, source="hybrid", evidence_score=30.0, score=0.9),
            _chunk(3, source="keyword", evidence_score=30.0, score=0.8),
        ],
        {"vector": 0.42, "keyword": 30.0, "graph": 0.0},
    )
    _clear_degradation_traces()
    try:
        with _session() as db:
            result = rerank_chunks(LITERAL_QUESTION, candidates, settings, db=db, top_k=5)
    finally:
        _clear_degradation_traces()

    assert [chunk.knowledge_id for chunk in result] == [1, 2, 3], "恒等保序"
    assert [chunk.score for chunk in result] == [1.0, 0.9, 0.8], "score 保持召回那一步的结果"
    assert result.evidence == candidates.evidence, "臂内证据集要原样带过去给分臂判定用"
    assert _degradation_rows() == [], "跳过不是降级，不记留痕"


# --- 回放模式（S6）：预置分与顺序一个字不改 ---

REPLAY_QUESTION = "产品的费率包含哪些项目？"


def test_replay_mode_leaves_the_preset_chunks_verbatim(monkeypatch):
    """S6：回放下的检索结果与改动前一致——预置分既不重写成模型相关性，也不被归一化。"""

    def _fail(*_args, **_kwargs):
        raise AssertionError("回放模式不该发起任何模型调用")

    monkeypatch.setattr(provider, "_request_chat", _fail)
    settings = get_settings().model_copy(
        update={"demo_replay": True, "llm_api_key": "test-key"}
    )

    with _session() as db:
        candidates = search_chunks(
            db,
            settings,
            query=REPLAY_QUESTION,
            top_k=settings.hybrid_recall_top_k,
        )
        result = rerank_chunks(REPLAY_QUESTION, candidates, settings, db=db, top_k=5)

    def _shape(chunks):
        return [
            (chunk.knowledge_id, chunk.chunk_index, chunk.score, chunk.evidence_score)
            for chunk in chunks
        ]

    assert candidates, "预置问题应命中预置分块"
    assert _shape(result) == _shape(candidates)
    assert [chunk.score for chunk in result] == [0.90], "预置分原样保留，不被重写"


# --- 模型只排了一部分候选 ---


def test_candidates_the_model_did_not_rank_land_last_with_a_zero_relevance(monkeypatch):
    """成功路径上 `score` 只有「模型相关性」一种量纲：没被排到的记 0 并沉到尾部。"""
    monkeypatch.setattr(
        provider,
        "_request_chat",
        lambda *a, **k: '{"ranking": [{"index": 2, "score": 0.5}]}',
    )
    settings = get_settings().model_copy(
        update={"llm_api_base": "http://llm.invalid/v1", "llm_api_key": "test-key"}
    )
    candidates = [
        _chunk(index, evidence_score=0.42, score=0.99) for index in range(1, 4)
    ]

    _clear_degradation_traces()
    try:
        with _session() as db:
            result = rerank_chunks(LITERAL_QUESTION, candidates, settings, db=db, top_k=5)
    finally:
        _clear_degradation_traces()

    assert [chunk.knowledge_id for chunk in result] == [2, 1, 3]
    assert [chunk.score for chunk in result] == [0.5, 0.0, 0.0]


# --- HTTP 层：保底占位与超时降级 ---


def test_rerank_keeps_a_qualified_chunk_inside_the_context(rerank_client, monkeypatch):
    """端到端：模型把达标块排到最后，它仍在送进模型的上下文里，且拿到模型给的分。"""
    _override_settings(llm_api_base="http://llm.invalid/v1", llm_api_key="test-key")
    unqualified = [_chunk(index, evidence_score=0.42, score=0.9) for index in range(1, 6)]
    qualified = _chunk(99, source="keyword", evidence_score=30.0, score=0.8)
    monkeypatch.setattr(
        agent_graph,
        "search_chunks",
        lambda *a, **k: RetrievedChunks(
            [*unqualified, qualified],
            {"vector": 0.42, "keyword": 30.0, "graph": 0.0},
        ),
    )
    # 模型给的顺序把达标块放在最末：若没有保底，它会因为只取前 5 条而被挤掉。
    monkeypatch.setattr(
        provider,
        "_request_chat",
        lambda *a, **k: _ranking_response([1, 2, 3, 4, 5, 6]),
    )

    captured: list[list[ChunkResult]] = []

    def _capture(question, history, chunks, settings):
        captured.append(list(chunks))
        return GroundedAnswer(text="略", cited_chunk_numbers=[1])

    monkeypatch.setattr(agent_graph, "generate_grounded_answer", _capture)

    token, _ = _customer_login(rerank_client)
    assert _chat(rerank_client, token, LITERAL_QUESTION).status_code == 200

    context = captured[0]
    assert len(context) == 5, "最终上下文取 AgentConfig 的 retrieval_top_k"
    assert [chunk.knowledge_id for chunk in context] == [1, 2, 3, 4, 99]
    assert context[-1].score == 0.4, "score 写模型给的相关性（保底块也不例外）"


def test_rerank_timeout_falls_back_to_the_rrf_order_and_still_answers(
    rerank_client, monkeypatch
):
    """重排超时只是回到 RRF 序并记一条 `rerank/timeout`，回答照常产出。"""
    _override_settings(llm_api_base="http://llm.invalid/v1", llm_api_key="test-key")
    candidates = RetrievedChunks(
        [
            _chunk(1, source="keyword", evidence_score=30.0, score=1.0),
            _chunk(2, evidence_score=0.42, score=0.9),
        ],
        {"vector": 0.42, "keyword": 30.0, "graph": 0.0},
    )
    monkeypatch.setattr(agent_graph, "search_chunks", lambda *a, **k: candidates)

    def _timeout(*_args, **_kwargs):
        raise TimeoutError("重排调用超时")

    monkeypatch.setattr(provider, "_request_chat", _timeout)

    captured: list[list[ChunkResult]] = []

    def _capture(question, history, chunks, settings):
        captured.append(list(chunks))
        return GroundedAnswer(text="略", cited_chunk_numbers=[1])

    monkeypatch.setattr(agent_graph, "generate_grounded_answer", _capture)

    token, _ = _customer_login(rerank_client)
    response = _chat(rerank_client, token, LITERAL_QUESTION)

    assert response.status_code == 200
    assert response.json()["data"]["answer"]
    assert [chunk.knowledge_id for chunk in captured[0]] == [1, 2], "退回 RRF 序"
    assert [chunk.score for chunk in captured[0]] == [1.0, 0.9]

    rows = _degradation_rows()
    assert [(row.dependency, row.reason) for row in rows] == [("rerank", "timeout")]
    assert response.json()["data"]["degraded"] is True


def test_unreachable_rerank_records_unavailable_and_does_not_block_the_answer(
    rerank_client, monkeypatch
):
    """失败（不是慢）走同一条退回，只把原因记成「不可达」。"""
    _override_settings(llm_api_base="http://llm.invalid/v1", llm_api_key="test-key")
    candidates = RetrievedChunks(
        [_chunk(1, source="keyword", evidence_score=30.0, score=1.0)],
        {"vector": 0.0, "keyword": 30.0, "graph": 0.0},
    )
    monkeypatch.setattr(agent_graph, "search_chunks", lambda *a, **k: candidates)

    def _broken(*_args, **_kwargs):
        raise ConnectionError("模型不可达")

    monkeypatch.setattr(provider, "_request_chat", _broken)
    monkeypatch.setattr(
        agent_graph,
        "generate_grounded_answer",
        lambda question, history, chunks, settings: GroundedAnswer(
            text="略", cited_chunk_numbers=[1]
        ),
    )

    token, _ = _customer_login(rerank_client)
    assert _chat(rerank_client, token, LITERAL_QUESTION).status_code == 200

    rows = _degradation_rows()
    assert [(row.dependency, row.reason) for row in rows] == [("rerank", "unavailable")]


# --- HTTP 层：内部检索接口与聊天同一条流水线 ---


def test_internal_search_reranks_with_its_own_top_k(rerank_client, monkeypatch):
    """内部检索接口显式串一次重排，返回的是重排后的排名而不是 RRF 原序。"""
    _override_settings(llm_api_base="http://llm.invalid/v1", llm_api_key="test-key")
    monkeypatch.setattr(
        "app.api.knowledge.search_chunks",
        lambda *a, **k: RetrievedChunks(
            [
                _chunk(1, evidence_score=0.42, score=1.0),
                _chunk(2, evidence_score=0.42, score=0.9),
            ],
            {"vector": 0.42, "keyword": 0.0, "graph": 0.0},
        ),
    )
    monkeypatch.setattr(
        provider, "_request_chat", lambda *a, **k: _ranking_response([2, 1])
    )

    response = rerank_client.post(
        "/api/internal/knowledge/search",
        headers=_internal_headers(rerank_client),
        json={"query": LITERAL_QUESTION, "top_k": 2},
    )

    assert response.status_code == 200
    hits = response.json()["data"]["hits"]
    assert [hit["knowledge_id"] for hit in hits] == [2, 1]
    assert [hit["score"] for hit in hits] == [0.9, 0.8]
