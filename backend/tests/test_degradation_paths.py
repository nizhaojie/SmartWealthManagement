"""降级路径全覆盖（ticket 05）。

Seam：后端 HTTP 层。这一份用例固定的是同一件事的五个侧面——**外部依赖抖动时，
使用者拿到的是降级后的服务，不是错误**，而且每一次降级都在留痕里数得出来：

- 模型调用失败：退避重试 → 切备用 → 预设兜底回答（HTTP 层拿到 200 与兜底文案）；
- 向量检索超时：改走基于分块镜像的关键词检索，仍返回可用结果；
- 图谱不可用：关系图入口返回空图而不是 500；
- 缓存不可用：画像直连数据库，缓存恢复后回填；
- 事件总线不可用：核心链路照常，只留痕。

外加三件横切的事：超时阈值可配置、追踪标识进响应、降级频次与各 Agent 响应时间可统计。
纯函数（退避次数与间隔）单独测，见文件末尾。
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
import redis as redis_lib
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session as OrmSession

import app.agent.graph as agent_graph
import app.llm.provider as provider
from app import degradation
from app.customer_profile.service import CACHE_KEY_PREFIX
from app.db.models import Customer, DegradationTrace, KnowledgeChunk
from app.event_bus import RedisEventPublisher
from app.exceptions import AppError
from app.knowledge.service import (
    DEGRADED_VECTOR_TIMEOUT,
    DEGRADED_VECTOR_UNAVAILABLE,
    ChunkResult,
    keyword_search_chunks,
)
from app.knowledge_graph import graph_view
from app.knowledge_graph.graphrag import (
    DEGRADED_TIMEOUT,
    GraphAugmentation,
)
from app.llm.provider import (
    LLM_SERVICE_FAILED_CODE,
    LLM_SERVICE_FAILED_MESSAGE,
    model_failure_answer,
)
from app.main import app
from app.neo4j_client import get_neo4j
from app.redis_client import get_redis
from app.settings import get_settings

CUSTOMER_USERNAME = "wangc1"
EMPLOYEE_USERNAME = "advisor1"
SEEDED_PASSWORD = "Test@1234"
UNUSED_GRAPH_NAMESPACE = "wealth_test_degradation_paths_unused"

# 关键词问题与文档正文共享足够多的二字词，关键词路径因此能命中它。
FAQ_TEXT = "客户办理赎回业务后，资金将在三个工作日内到账。"
FAQ_QUESTION = "赎回的资金多久到账"


class _BrokenMethods:
    """把指定方法名变成会抛 RedisError 的缓存客户端，其余转发给真客户端。

    整台 Redis 都不可用时，鉴权（`auth.session_store` 的会话校验）会先失败——身份是
    不能靠猜的那一层，不在降级范围内。这里隔离出「缓存层抖动」：要测的画像缓存与
    短期记忆各自降级，而会话校验照常。
    """

    def __init__(self, inner, methods: set[str]) -> None:
        self._inner = inner
        self._methods = methods

    def __getattr__(self, name: str):
        if name in self._methods:
            def _raise(*_args, **_kwargs):
                raise redis_lib.RedisError("缓存不可用")

            return _raise
        return getattr(self._inner, name)


class _BrokenDriver:
    """Neo4j 掉线：拿会话就抛。"""

    def session(self):
        raise RuntimeError("neo4j 不可用")


class _FakeTime:
    """只拦截 sleep 的时间模块替身，避免把整个进程的 time.sleep 换掉。"""

    def __init__(self, sleeps: list[float]) -> None:
        self._sleeps = sleeps

    def sleep(self, seconds: float) -> None:
        self._sleeps.append(seconds)


def _test_settings(**overrides):
    base = get_settings()
    return base.model_copy(
        update={
            "milvus_collection": base.test_milvus_collection,
            "embedding_api_key": "",
            "llm_api_key": "",
            "neo4j_graph_namespace": UNUSED_GRAPH_NAMESPACE,
            # 关键词臂阈值显式注入：本文件验证的是「降级路径仍给出可用结果」，分界因此
            # 由用例自己掌握，不跟着校准值走。校准后的默认值（13.0，见 issue 04）量的是
            # 另一份语料上的分布：这里的目标分块在测试库的 FAQ 语料里只拿到约 11.5 分
            # （同主题的 faq_seed 分块稀释了 df），用默认值会把「降级成功」判成兜底。
            "retrieval_keyword_score_threshold": 10.0,
            # 退避等待置 0：这里验证的是「重试与切换发生了」，不是真的等 1s / 2s。
            "llm_retry_backoff_seconds": 0.0,
            **overrides,
        }
    )


@pytest.fixture
def degradation_client(auth_client: TestClient) -> Iterator[TestClient]:
    app.dependency_overrides[get_settings] = lambda: _test_settings()
    _clear_degradation_traces()
    try:
        yield auth_client
    finally:
        _clear_degradation_traces()
        app.dependency_overrides.pop(get_settings, None)


@contextmanager
def _override_redis(client):
    """临时替换缓存依赖，并在退出时**还原**原有覆盖。

    直接 pop 会把 auth_client 装的测试缓存覆盖一起摘掉，后续请求就落到开发库的
    Redis 上——登录态在那里不存在，于是「恢复后回填」那一步会莫名其妙地 401。
    """
    previous = app.dependency_overrides.get(get_redis)
    app.dependency_overrides[get_redis] = lambda: client
    try:
        yield
    finally:
        if previous is None:
            app.dependency_overrides.pop(get_redis, None)
        else:
            app.dependency_overrides[get_redis] = previous


def _engine():
    return create_engine(get_settings().test_database_url)


def _clear_degradation_traces() -> None:
    engine = _engine()
    try:
        with OrmSession(engine) as session:
            session.execute(delete(DegradationTrace))
            session.commit()
    finally:
        engine.dispose()


def _degradation_rows() -> list[DegradationTrace]:
    engine = _engine()
    try:
        with OrmSession(engine) as session:
            return list(
                session.scalars(select(DegradationTrace).order_by(DegradationTrace.id))
            )
    finally:
        engine.dispose()


def _customer_id() -> int:
    engine = _engine()
    try:
        with OrmSession(engine) as session:
            value = session.scalar(
                select(Customer.id).where(Customer.username == CUSTOMER_USERNAME)
            )
    finally:
        engine.dispose()
    assert value is not None
    return int(value)


def _customer_login(client: TestClient) -> str:
    response = client.post(
        "/api/customer/auth/login",
        json={"username": CUSTOMER_USERNAME, "password": SEEDED_PASSWORD},
    )
    return response.json()["data"]["access_token"]


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


def _upload(client: TestClient, *, filename: str, content: bytes, knowledge_type: str = "FAQ"):
    return client.post(
        "/api/internal/knowledge/documents",
        headers=_internal_headers(client),
        files={"file": (filename, content, "text/plain")},
        data={"knowledge_type": knowledge_type},
    )


def _delete_document(client: TestClient, knowledge_id: int):
    return client.delete(
        f"/api/internal/knowledge/documents/{knowledge_id}",
        headers=_internal_headers(client),
    )


def _snippet() -> ChunkResult:
    return ChunkResult(
        knowledge_id=9001,
        knowledge_type="FAQ",
        chunk_index=0,
        heading_path=[],
        content="本产品最短持有期为九十天。",
        score=0.99,
        title="产品要素说明",
        source_file="stub.txt",
        # 分臂判定读证据分：这块走的是向量臂，0.99 ≥ RETRIEVAL_SCORE_THRESHOLD。
        evidence_score=0.99,
    )


def _fail_model(*_args, **_kwargs):
    raise AppError(LLM_SERVICE_FAILED_CODE, LLM_SERVICE_FAILED_MESSAGE)


def _stub_graph(monkeypatch) -> None:
    """把图谱增强固定成「正常、不降级」，让用例只观察它要观察的那一条路径。"""
    monkeypatch.setattr(
        agent_graph, "augment_with_graph", lambda *a, **k: GraphAugmentation()
    )


# --- 模型调用：退避重试 → 备用 → 预设兜底 ---


def test_model_failure_returns_the_preset_answer_instead_of_an_error(
    degradation_client, monkeypatch
):
    """模型整体不可用时，使用者看到的是兜底文案，不是 500。"""
    _stub_graph(monkeypatch)
    monkeypatch.setattr(agent_graph, "search_chunks", lambda *a, **k: [_snippet()])
    monkeypatch.setattr(agent_graph, "generate_grounded_answer", _fail_model)

    token = _customer_login(degradation_client)
    response = _chat(degradation_client, token, "这个产品的期限是多久")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["answer"] == model_failure_answer(get_settings())
    # 兜底回答没有依据可引，引用为空——前端对空引用有专门的渲染用例。
    assert data["citations"] == []
    assert "95588" in data["answer"]
    assert data["degraded"] is True

    rows = _degradation_rows()
    assert [row.dependency for row in rows] == [degradation.DEPENDENCY_MODEL]
    assert rows[0].reason == degradation.REASON_RETRY_EXHAUSTED


def test_model_failure_in_chitchat_also_falls_back(degradation_client, monkeypatch):
    _stub_graph(monkeypatch)
    monkeypatch.setattr(agent_graph, "generate_chitchat_reply", _fail_model)

    token = _customer_login(degradation_client)
    response = _chat(degradation_client, token, "你好呀，今天天气不错")

    assert response.status_code == 200
    data = response.json()["data"]
    assert "95588" in data["answer"]
    assert data["degraded"] is True


# --- 向量检索超时 → 关键词检索 ---


def test_vector_search_timeout_falls_back_to_keyword_retrieval(
    degradation_client, monkeypatch
):
    _stub_graph(monkeypatch)
    upload = _upload(
        degradation_client,
        filename="test_degradation_keyword.txt",
        content=FAQ_TEXT.encode("utf-8"),
        knowledge_type="FAQ",
    )
    knowledge_id = upload.json()["data"]["knowledge_id"]

    # 向量臂的替身一直阻塞到用例放行：软超时不看它收尾，所以只要它在预算用光时
    # 还没返回，超时就一定发生。**不能用固定 sleep**——超时预算从提交那一刻起算，
    # 关键词臂在主线程里花掉的时间要从预算里扣，而 jieba 冷启动一次接近 1s（隔离
    # 运行本文件时就是这种情形），比 0.4s 的 sleep 还长，future 会先跑完、超时不再发生。
    release_vector_arm = threading.Event()

    def _blocked(*_args, **_kwargs):
        release_vector_arm.wait(timeout=30)
        return []

    monkeypatch.setattr("app.knowledge.service._vector_search_hits", _blocked)
    # 超时阈值可配置：这里把它调到 0.1s，让上面那个不会返回的调用真的超时。
    app.dependency_overrides[get_settings] = lambda: _test_settings(
        vector_search_timeout_seconds=0.1
    )

    try:
        token = _customer_login(degradation_client)
        response = _chat(degradation_client, token, FAQ_QUESTION)

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["citations"], "关键词兜底仍应返回可用结果"
        assert data["citations"][0]["knowledge_id"] == knowledge_id
        assert data["degraded"] is True
    finally:
        release_vector_arm.set()
        _delete_document(degradation_client, knowledge_id)

    rows = _degradation_rows()
    assert (rows[0].dependency, rows[0].reason) == (
        degradation.DEPENDENCY_VECTOR,
        DEGRADED_VECTOR_TIMEOUT,
    )


def test_vector_search_error_falls_back_to_keyword_retrieval(
    degradation_client, monkeypatch
):
    """向量库整个不可用（不是慢）走同一条兜底，只把原因记成「不可达」。"""
    _stub_graph(monkeypatch)
    upload = _upload(
        degradation_client,
        filename="test_degradation_unavailable.txt",
        content=FAQ_TEXT.encode("utf-8"),
        knowledge_type="FAQ",
    )
    knowledge_id = upload.json()["data"]["knowledge_id"]

    def _broken(*_args, **_kwargs):
        raise ConnectionError("向量库不可达")

    monkeypatch.setattr("app.knowledge.service._vector_search_hits", _broken)

    try:
        token = _customer_login(degradation_client)
        response = _chat(degradation_client, token, FAQ_QUESTION)

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["citations"][0]["knowledge_id"] == knowledge_id
        assert data["degraded"] is True
    finally:
        _delete_document(degradation_client, knowledge_id)

    rows = _degradation_rows()
    assert (rows[0].dependency, rows[0].reason) == (
        degradation.DEPENDENCY_VECTOR,
        DEGRADED_VECTOR_UNAVAILABLE,
    )


def test_keyword_arm_scores_by_bm25_and_ignores_chunks_of_expired_documents(
    degradation_client,
):
    """关键词臂按 BM25 打分，可见性与向量路径口径一致：过期文档不因降级而复活。"""
    upload = _upload(
        degradation_client,
        filename="test_degradation_expired.txt",
        content=FAQ_TEXT.encode("utf-8"),
        knowledge_type="FAQ",
    )
    knowledge_id = upload.json()["data"]["knowledge_id"]

    engine = _engine()
    try:
        with OrmSession(engine) as session:
            active_hits = keyword_search_chunks(
                session, query=FAQ_QUESTION, knowledge_type="FAQ"
            )
        assert any(hit.knowledge_id == knowledge_id for hit in active_hits), "BM25 应命中"
        assert all(hit.evidence_score > 0 for hit in active_hits)
        assert all(hit.source == "keyword" for hit in active_hits)

        _delete_document(degradation_client, knowledge_id)

        with OrmSession(engine) as session:
            leftover = session.scalar(
                select(KnowledgeChunk.id).where(KnowledgeChunk.knowledge_id == knowledge_id)
            )
            assert leftover is not None, "镜像行不随删除消失，可见性靠文档状态过滤"

        with OrmSession(engine) as session:
            expired_hits = keyword_search_chunks(
                session, query=FAQ_QUESTION, knowledge_type="FAQ"
            )
    finally:
        engine.dispose()

    assert all(hit.knowledge_id != knowledge_id for hit in expired_hits)


# --- 图谱不可用 → 空图而不是 500 ---


def test_unavailable_graph_returns_an_empty_degraded_view(degradation_client):
    previous = app.dependency_overrides.get(get_neo4j)
    app.dependency_overrides[get_neo4j] = lambda: _BrokenDriver()
    try:
        response = degradation_client.get(
            f"/api/internal/graph/customers/{_customer_id()}",
            headers=_internal_headers(degradation_client),
        )
    finally:
        if previous is None:
            app.dependency_overrides.pop(get_neo4j, None)
        else:
            app.dependency_overrides[get_neo4j] = previous

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["degraded"] is True
    assert data["nodes"] == []
    assert data["edges"] == []

    rows = _degradation_rows()
    assert (rows[0].dependency, rows[0].reason) == (
        degradation.DEPENDENCY_GRAPH,
        graph_view.DEGRADED_UNAVAILABLE,
    )


def test_graph_degradation_in_a_chat_turn_is_recorded_not_silently_swallowed(
    degradation_client, monkeypatch
):
    """聊天里的图谱降级也要进降级留痕：spec 要求「每一处降级都能统计到」。"""
    monkeypatch.setattr(agent_graph, "search_chunks", lambda *a, **k: [_snippet()])
    monkeypatch.setattr(
        agent_graph,
        "augment_with_graph",
        lambda *a, **k: GraphAugmentation(
            degraded=True,
            degradation_reason=DEGRADED_TIMEOUT,
        ),
    )

    token = _customer_login(degradation_client)
    response = _chat(degradation_client, token, "这个产品的期限是多久")

    assert response.status_code == 200
    assert response.json()["data"]["degraded"] is True

    rows = _degradation_rows()
    assert [(row.dependency, row.reason) for row in rows] == [
        (degradation.DEPENDENCY_GRAPH, degradation.REASON_TIMEOUT)
    ]
    # 图谱自己的细分原因留在 detail 里，统计口径仍然统一。
    assert rows[0].detail == DEGRADED_TIMEOUT


# --- 缓存不可用 → 直连数据库，恢复后回填 ---


def test_profile_is_readable_without_cache_and_refilled_after_recovery(degradation_client):
    customer_id = _customer_id()
    headers = _internal_headers(degradation_client)
    test_redis = redis_lib.Redis.from_url(get_settings().test_redis_url, decode_responses=True)
    test_redis.delete(f"{CACHE_KEY_PREFIX}{customer_id}")

    with _override_redis(_BrokenMethods(test_redis, {"get", "set", "delete"})):
        degraded = degradation_client.get(
            f"/api/internal/customers/{customer_id}/profile", headers=headers
        )

    assert degraded.status_code == 200
    assert degraded.json()["data"]["tags"], "缓存不可用时画像仍应从数据库读出来"

    rows = _degradation_rows()
    assert [row.dependency for row in rows] == [degradation.DEPENDENCY_CACHE]

    # 缓存恢复后再读一次：Cache-Aside 自动回填，不需要额外的补偿任务。
    try:
        recovered = degradation_client.get(
            f"/api/internal/customers/{customer_id}/profile", headers=headers
        )
        assert recovered.status_code == 200
        assert test_redis.get(f"{CACHE_KEY_PREFIX}{customer_id}") is not None
    finally:
        test_redis.delete(f"{CACHE_KEY_PREFIX}{customer_id}")
        test_redis.close()


def test_chat_turn_survives_an_unavailable_cache(degradation_client, monkeypatch):
    """短期记忆的缓存抖动不该让整轮对话失败：退化成没有上下文的一轮，照常作答。"""
    monkeypatch.setattr(agent_graph, "search_chunks", lambda *a, **k: [])
    test_redis = redis_lib.Redis.from_url(get_settings().test_redis_url, decode_responses=True)

    token = _customer_login(degradation_client)
    try:
        with _override_redis(
            _BrokenMethods(test_redis, {"lrange", "rpush", "expire", "ltrim"})
        ):
            response = _chat(
                degradation_client, token, "阿尔法半人马座恒星系统的行星编号列表是什么"
            )
    finally:
        test_redis.close()

    assert response.status_code == 200
    assert response.json()["data"]["answer"]
    assert degradation.DEPENDENCY_CACHE in [row.dependency for row in _degradation_rows()]


# --- 事件总线不可用 → 核心链路继续，仅留痕 ---


def test_unavailable_event_bus_does_not_break_the_chat_turn(degradation_client, monkeypatch):
    monkeypatch.setattr(agent_graph, "search_chunks", lambda *a, **k: [])

    def _explode(self, event):
        raise ConnectionError("事件总线不可用")

    monkeypatch.setattr(RedisEventPublisher, "publish", _explode)

    token = _customer_login(degradation_client)
    response = _chat(degradation_client, token, "我想问下我的转账限额是多少")

    assert response.status_code == 200
    assert response.json()["data"]["answer"]
    assert degradation.DEPENDENCY_EVENT_BUS in [
        row.dependency for row in _degradation_rows()
    ]


# --- 追踪标识与统计 ---


def test_trace_id_travels_with_the_response(degradation_client):
    token = _customer_login(degradation_client)
    response = _chat(degradation_client, token, "你好呀")

    trace_id = response.json()["data"]["trace_id"]
    assert trace_id
    assert response.headers["x-trace-id"] == trace_id


def test_degradation_frequency_and_response_times_are_queryable(
    degradation_client, monkeypatch
):
    _stub_graph(monkeypatch)
    monkeypatch.setattr(agent_graph, "search_chunks", lambda *a, **k: [_snippet()])
    monkeypatch.setattr(agent_graph, "generate_grounded_answer", _fail_model)

    token = _customer_login(degradation_client)
    _chat(degradation_client, token, "这个产品的期限是多久")

    headers = _internal_headers(degradation_client)
    stats = degradation_client.get("/api/internal/traces/degradations", headers=headers)
    assert stats.status_code == 200
    body = stats.json()["data"]
    assert body["total"] >= 1
    assert body["by_dependency"][degradation.DEPENDENCY_MODEL] >= 1
    assert body["by_reason"][degradation.REASON_RETRY_EXHAUSTED] >= 1

    times = degradation_client.get(
        "/api/internal/traces/agent-response-times", headers=headers
    )
    assert times.status_code == 200
    agents = {row["agent_type"]: row for row in times.json()["data"]["agents"]}
    assert "customer_service" in agents
    assert agents["customer_service"]["count"] >= 1
    assert agents["customer_service"]["avg_duration_ms"] >= 0


def test_degradation_stats_require_internal_identity(degradation_client):
    assert degradation_client.get("/api/internal/traces/degradations").status_code == 401


# --- 纯函数：退避重试与备用切换 ---


def _llm_settings(**overrides):
    return get_settings().model_copy(
        update={
            "llm_api_base": "http://primary.invalid/v1",
            "llm_api_key": "primary-key",
            "llm_model_name": "primary-model",
            "llm_backup_api_base": "http://backup.invalid/v1",
            "llm_backup_api_key": "backup-key",
            "llm_backup_model_name": "backup-model",
            "llm_max_retries": 3,
            "llm_retry_backoff_seconds": 0.0,
            **overrides,
        }
    )


def test_chat_completion_retries_then_switches_to_the_backup_endpoint(monkeypatch):
    calls: list[str] = []

    def _request(endpoint, messages, *, timeout):
        calls.append(endpoint.label)
        if endpoint.label == "primary":
            raise ConnectionError("主配置不可用")
        return "备用配置的回答"

    monkeypatch.setattr(provider, "_request_chat", _request)

    answer = provider.chat_completion(
        [{"role": "user", "content": "你好"}], _llm_settings()
    )

    assert answer == "备用配置的回答"
    # 需求文档：间隔 1s/2s/4s、最多 3 次 -> 主配置 1 次 + 重试 3 次，再换备用配置。
    assert calls == ["primary", "primary", "primary", "primary", "backup"]


def test_chat_completion_waits_with_exponential_backoff(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr(provider, "time", _FakeTime(sleeps))
    monkeypatch.setattr(
        provider,
        "_request_chat",
        lambda *a, **k: (_ for _ in ()).throw(ConnectionError("不可用")),
    )

    with pytest.raises(AppError) as raised:
        provider.chat_completion(
            [{"role": "user", "content": "你好"}],
            _llm_settings(llm_backup_api_key="", llm_retry_backoff_seconds=1.0),
        )

    assert raised.value.code == LLM_SERVICE_FAILED_CODE
    # 3 次重试 -> 间隔按 1s / 2s / 4s 翻倍；备用未配置时整条跳过。
    assert sleeps == [1.0, 2.0, 4.0]


def test_chat_completion_without_a_usable_endpoint_fails_fast(monkeypatch):
    def _unexpected(*_args, **_kwargs):
        raise AssertionError("没有可用配置时不该发起调用")

    monkeypatch.setattr(provider, "_request_chat", _unexpected)

    with pytest.raises(AppError):
        provider.chat_completion(
            [{"role": "user", "content": "你好"}],
            _llm_settings(llm_api_key="", llm_backup_api_key=""),
        )


def test_chat_completion_with_an_explicit_endpoint_bypasses_primary_and_backup(
    monkeypatch,
):
    """重排专用模型（rerank_endpoint）显式给定配置时，主/备整条链路被绕开。"""
    calls: list[tuple[str, str]] = []

    def _request(endpoint, messages, *, timeout):
        calls.append((endpoint.label, endpoint.model_name))
        return "专用模型的回答"

    monkeypatch.setattr(provider, "_request_chat", _request)

    settings = _llm_settings(
        rerank_llm_model_name="rerank-model",
        rerank_llm_api_base="http://rerank.invalid/v1",
        rerank_llm_api_key="rerank-key",
    )
    answer = provider.chat_completion(
        [{"role": "user", "content": "排序"}],
        settings,
        endpoint=provider.rerank_endpoint(settings),
    )

    assert answer == "专用模型的回答"
    assert calls == [("rerank", "rerank-model")], "只调专用配置这一份，不重试不切备用"


def test_rerank_endpoint_falls_back_to_none_when_not_fully_configured():
    """三个 rerank_llm_* 没配全时返回 None（回落主配置），存量 .env 行为不变。"""
    settings = _llm_settings(
        rerank_llm_model_name="rerank-model",
        rerank_llm_api_base="",
        rerank_llm_api_key="rerank-key",
    )

    assert provider.rerank_endpoint(settings) is None


def test_risk_monitoring_agent_type_literal_matches_the_agent_config():
    """风控链路为了不引入模型层而写死的 Agent 名，必须与配置里的取值一致。"""
    from app.agent.config import RISK_MONITORING_CONFIG
    from app.risk_monitoring.alerting import AGENT_TYPE_RISK_MONITORING

    assert AGENT_TYPE_RISK_MONITORING == RISK_MONITORING_CONFIG.name
