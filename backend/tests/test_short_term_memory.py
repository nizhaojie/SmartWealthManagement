"""短期记忆：滑动过期、超长对话截断而不报错（ADR-0012 第一层）。"""

from collections.abc import Iterator
from uuid import uuid4

import jwt as pyjwt
import pytest
import redis as redis_lib
from fastapi.testclient import TestClient

from app.agent import memory as agent_memory
from app.main import app
from app.settings import get_settings

SEEDED_PASSWORD = "Test@1234"
CUSTOMER_USERNAME = "wangc1"


@pytest.fixture
def chat_client(auth_client: TestClient) -> Iterator[TestClient]:
    base_settings = get_settings()
    test_settings = base_settings.model_copy(
        update={
            "milvus_collection": base_settings.test_milvus_collection,
            "embedding_api_key": "",
            "llm_api_key": "",
            "neo4j_graph_namespace": "wealth_test_customer_service_agent_unused",
        }
    )
    app.dependency_overrides[get_settings] = lambda: test_settings
    try:
        yield auth_client
    finally:
        app.dependency_overrides.pop(get_settings, None)


@pytest.fixture
def redis_cache() -> Iterator[redis_lib.Redis]:
    cache = redis_lib.Redis.from_url(get_settings().test_redis_url, decode_responses=True)
    try:
        yield cache
    finally:
        cache.close()


def _memory_key(session_id: str) -> str:
    return f"agent:memory:{session_id}"


def _customer_login(client: TestClient) -> tuple[str, str]:
    response = client.post(
        "/api/customer/auth/login",
        json={"username": CUSTOMER_USERNAME, "password": SEEDED_PASSWORD},
    )
    token = response.json()["data"]["access_token"]
    session_id = pyjwt.decode(token, options={"verify_signature": False})["sid"]
    return token, session_id


def test_each_turn_slides_the_expiry_window(redis_cache):
    settings = get_settings().model_copy(update={"chat_memory_ttl_minutes": 1})
    session_id = f"test-memory-ttl-{uuid4()}"
    key = _memory_key(session_id)

    try:
        agent_memory.append_turn(
            redis_cache, session_id, role="user", content="你好呀", settings=settings
        )
        # 把 TTL 压到接近过期，再追加一轮：窗口应当被推回完整的 1 分钟。
        redis_cache.expire(key, 5)
        assert redis_cache.ttl(key) <= 5

        agent_memory.append_turn(
            redis_cache, session_id, role="assistant", content="你好", settings=settings
        )

        assert redis_cache.ttl(key) > 30
    finally:
        redis_cache.delete(key)


def test_extremely_long_conversation_truncates_oldest_and_keeps_latest(redis_cache):
    settings = get_settings().model_copy(update={"chat_memory_token_budget": 10})
    session_id = f"test-memory-long-{uuid4()}"
    key = _memory_key(session_id)
    last_content = "这是第199条消息，请记住它"

    try:
        for index in range(200):
            agent_memory.append_turn(
                redis_cache,
                session_id,
                role="user",
                content=f"这是第{index}条消息，请记住它",
                settings=settings,
            )

        history = agent_memory.get_history(redis_cache, session_id)

        # 每一条都超过预算，因此最终只剩最新的一条——超长对话不报错，且最新消息保留。
        assert history == [{"role": "user", "content": last_content}]
    finally:
        redis_cache.delete(key)


def test_long_conversation_over_http_stays_within_budget(chat_client, redis_cache):
    base_settings = get_settings()
    settings = base_settings.model_copy(
        update={
            "milvus_collection": base_settings.test_milvus_collection,
            "embedding_api_key": "",
            "llm_api_key": "",
            "neo4j_graph_namespace": "wealth_test_customer_service_agent_unused",
            "chat_memory_token_budget": 5,
        }
    )
    app.dependency_overrides[get_settings] = lambda: settings
    token, session_id = _customer_login(chat_client)
    key = _memory_key(session_id)

    try:
        for _ in range(6):
            response = chat_client.post(
                "/api/customer/chat/messages",
                headers={"Authorization": f"Bearer {token}"},
                json={"message": "你好呀"},
            )
            assert response.status_code == 200

        history = agent_memory.get_history(redis_cache, session_id)
        assert history, "预算截断不应把上下文清空——最新消息必须留下"
        assert len(history) <= 4
    finally:
        redis_cache.delete(key)
        app.dependency_overrides.pop(get_settings, None)
