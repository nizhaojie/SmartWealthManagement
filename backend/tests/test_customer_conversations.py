"""客户历史记录：客户只能查看自己身份域下的历史会话，只读回看。

与内部端 `conversation_archive` 查询共用同一张表，但走客户身份域（`require_customer`），
可见范围收紧到「自己」：列表排除当前会话、只含本人的会话；详情不暴露 tool_calls 与
content_classification 等内部/合规字段。
"""

from collections.abc import Iterator

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.settings import get_settings

SEEDED_PASSWORD = "Test@1234"
CUSTOMER_USERNAME = "wangc1"
OTHER_CUSTOMER_USERNAME = "zhaoc4"
ADVISOR_USERNAME = "advisor1"


@pytest.fixture
def chat_client(auth_client: TestClient) -> Iterator[TestClient]:
    base_settings = get_settings()
    test_settings = base_settings.model_copy(
        update={
            "milvus_collection": base_settings.test_milvus_collection,
            "embedding_api_key": "",
            "llm_api_key": "",
            # 与 test_customer_service_agent.py 同一理由：稳定走空图谱降级。
            "neo4j_graph_namespace": "wealth_test_customer_history_unused",
        }
    )
    app.dependency_overrides[get_settings] = lambda: test_settings
    try:
        yield auth_client
    finally:
        app.dependency_overrides.pop(get_settings, None)


def _customer_login(client: TestClient, username: str) -> tuple[str, str, int]:
    response = client.post(
        "/api/customer/auth/login",
        json={"username": username, "password": SEEDED_PASSWORD},
    )
    token = response.json()["data"]["access_token"]
    payload = pyjwt.decode(token, options={"verify_signature": False})
    return token, payload["sid"], int(payload["sub"])


def _chat(client: TestClient, token: str, message: str):
    return client.post(
        "/api/customer/chat/messages",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": message},
    )


def _list_history(client: TestClient, token: str):
    return client.get(
        "/api/customer/conversations",
        headers={"Authorization": f"Bearer {token}"},
    )


def _get_history(client: TestClient, token: str, session_id: str):
    return client.get(
        f"/api/customer/conversations/{session_id}",
        headers={"Authorization": f"Bearer {token}"},
    )


def test_customer_lists_own_history_excluding_current_session(chat_client):
    token1, sid1, user1 = _customer_login(chat_client, CUSTOMER_USERNAME)
    _chat(chat_client, token1, "第一场的第一句提问")

    token2, sid2, user2 = _customer_login(chat_client, CUSTOMER_USERNAME)
    assert user1 == user2
    _chat(chat_client, token2, "第二场的第一句提问")

    listing = _list_history(chat_client, token2)
    assert listing.status_code == 200
    sessions = listing.json()["data"]["items"]
    session_ids = {item["session_id"] for item in sessions}

    # 当前会话不在历史里，过去的会话在。
    assert sid1 in session_ids
    assert sid2 not in session_ids

    first = next(item for item in sessions if item["session_id"] == sid1)
    assert first["title"] == "第一场的第一句提问"
    assert first["message_count"] == 2  # 一问一答两条归档
    assert first["started_at"] <= first["ended_at"]


def test_customer_history_hides_other_customers_sessions(chat_client):
    token_a, sid_a, _ = _customer_login(chat_client, CUSTOMER_USERNAME)
    _chat(chat_client, token_a, "A 的提问")
    token_b, sid_b, _ = _customer_login(chat_client, OTHER_CUSTOMER_USERNAME)
    _chat(chat_client, token_b, "B 的提问")

    items_a = _list_history(chat_client, token_a).json()["data"]["items"]
    session_ids_a = {item["session_id"] for item in items_a}
    assert sid_a not in session_ids_a  # 当前会话排除
    assert sid_b not in session_ids_a  # 别人的会话不可见

    items_b = _list_history(chat_client, token_b).json()["data"]["items"]
    session_ids_b = {item["session_id"] for item in items_b}
    assert sid_b not in session_ids_b
    assert sid_a not in session_ids_b


def test_customer_reads_own_session_detail_without_internal_fields(chat_client):
    token, sid, _ = _customer_login(chat_client, CUSTOMER_USERNAME)
    _chat(chat_client, token, "你好呀")

    detail = _get_history(chat_client, token, sid)
    assert detail.status_code == 200
    data = detail.json()["data"]
    assert data["session_id"] == sid

    messages = data["messages"]
    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert messages[0]["content"] == "你好呀"

    # 只读回看：详情只给 role / content / citations / 时间，内部与合规字段不外泄。
    for message in messages:
        assert set(message.keys()) <= {"role", "content", "citations", "created_at"}
    assert isinstance(messages[1]["citations"], list)


def test_customer_cannot_read_foreign_or_unknown_session(chat_client):
    token_a, sid_a, _ = _customer_login(chat_client, CUSTOMER_USERNAME)
    _chat(chat_client, token_a, "A 的提问")

    token_b, _, _ = _customer_login(chat_client, OTHER_CUSTOMER_USERNAME)

    # 别人的会话：即使拿到 session_id 也查不到（不暴露存在性）。
    assert _get_history(chat_client, token_b, sid_a).status_code == 404
    # 不存在的会话。
    assert _get_history(chat_client, token_b, "no-such-session").status_code == 404


def test_customer_history_endpoints_require_customer_identity(chat_client):
    # 未认证。
    assert chat_client.get("/api/customer/conversations").status_code == 401

    # 内部员工凭证在客户端点上无效（身份域隔离，ADR-0009 护栏 2）。
    login = chat_client.post(
        "/api/internal/auth/login",
        json={"username": ADVISOR_USERNAME, "password": SEEDED_PASSWORD},
    )
    internal_token = login.json()["data"]["access_token"]
    response = chat_client.get(
        "/api/customer/conversations",
        headers={"Authorization": f"Bearer {internal_token}"},
    )
    assert response.status_code == 403
