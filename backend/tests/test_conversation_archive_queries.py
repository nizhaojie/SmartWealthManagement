"""会话归档查询（Seam 1）：按会话标识或用户标识回溯历史会话，且不越权。"""

from collections.abc import Iterator

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.settings import get_settings

SEEDED_PASSWORD = "Test@1234"
ADVISOR_USERNAME = "advisor1"
MANAGER1_USERNAME = "manager1"
CUSTOMER_USERNAME = "wangc1"
OTHER_CUSTOMER_USERNAME = "zhaoc4"


@pytest.fixture
def chat_client(auth_client: TestClient) -> Iterator[TestClient]:
    base_settings = get_settings()
    test_settings = base_settings.model_copy(
        update={
            "milvus_collection": base_settings.test_milvus_collection,
            "embedding_api_key": "",
            "llm_api_key": "",
            # 与 test_customer_service_agent.py 同一理由：稳定走空图谱降级，
            # 避免别的测试模块重建过命名空间而引入跨文件耦合。
            "neo4j_graph_namespace": "wealth_test_customer_service_agent_unused",
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


def _internal_token(client: TestClient, username: str) -> str:
    response = client.post(
        "/api/internal/auth/login",
        json={"username": username, "password": SEEDED_PASSWORD},
    )
    return response.json()["data"]["access_token"]


def _chat(client: TestClient, token: str, message: str):
    return client.post(
        "/api/customer/chat/messages",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": message},
    )


def _list_sessions(client: TestClient, token: str, **params):
    return client.get(
        "/api/internal/conversations",
        params=params,
        headers={"Authorization": f"Bearer {token}"},
    )


def _get_session(client: TestClient, token: str, session_id: str):
    return client.get(
        f"/api/internal/conversations/{session_id}",
        headers={"Authorization": f"Bearer {token}"},
    )


def test_transcript_is_fetchable_by_session_id(chat_client):
    token, session_id, user_id = _customer_login(chat_client, CUSTOMER_USERNAME)
    _chat(chat_client, token, "你好呀")
    _chat(chat_client, token, "再问一句你好")

    internal = _internal_token(chat_client, ADVISOR_USERNAME)

    listing = _list_sessions(chat_client, internal, session_id=session_id)
    assert listing.status_code == 200
    sessions = listing.json()["data"]["items"]
    assert [item["session_id"] for item in sessions] == [session_id]
    assert sessions[0]["user_id"] == user_id
    assert sessions[0]["identity_domain"] == "customer"
    assert sessions[0]["message_count"] == 4

    detail = _get_session(chat_client, internal, session_id)
    assert detail.status_code == 200
    messages = detail.json()["data"]["messages"]
    assert [message["role"] for message in messages] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    assert messages[0]["content"] == "你好呀"


def test_sessions_are_listable_by_user_id(chat_client):
    token, session_id, user_id = _customer_login(chat_client, CUSTOMER_USERNAME)
    _chat(chat_client, token, "你好呀")

    internal = _internal_token(chat_client, ADVISOR_USERNAME)
    listing = _list_sessions(chat_client, internal, user_id=user_id)

    assert listing.status_code == 200
    sessions = listing.json()["data"]["items"]
    assert session_id in {item["session_id"] for item in sessions}
    assert all(item["user_id"] == user_id for item in sessions)


def test_unknown_session_is_not_found(chat_client):
    internal = _internal_token(chat_client, ADVISOR_USERNAME)
    response = _get_session(chat_client, internal, "no-such-session")
    assert response.status_code == 404


def test_conversation_endpoints_require_internal_identity(chat_client):
    assert chat_client.get("/api/internal/conversations").status_code == 401

    customer_token, _, _ = _customer_login(chat_client, CUSTOMER_USERNAME)
    response = _list_sessions(chat_client, customer_token)
    # 客户凭证在内部端点上一律无效（ADR-0004 身份域隔离）。
    assert response.status_code == 403


def test_account_manager_only_reaches_own_customers_sessions(chat_client):
    own_token, own_session, own_user = _customer_login(chat_client, CUSTOMER_USERNAME)
    _chat(chat_client, own_token, "你好呀")
    other_token, other_session, other_user = _customer_login(chat_client, OTHER_CUSTOMER_USERNAME)
    _chat(chat_client, other_token, "你好呀")

    manager1 = _internal_token(chat_client, MANAGER1_USERNAME)

    assert _list_sessions(chat_client, manager1, user_id=other_user).json()["data"]["items"] == []
    assert _get_session(chat_client, manager1, other_session).status_code == 403
    assert _get_session(chat_client, manager1, own_session).status_code == 200

    # 不受限的角色看得到全部，限制只落在客户经理身上。
    advisor = _internal_token(chat_client, ADVISOR_USERNAME)
    visible = {
        item["session_id"]
        for item in _list_sessions(chat_client, advisor).json()["data"]["items"]
    }
    assert {own_session, other_session} <= visible
    assert _get_session(chat_client, advisor, other_session).status_code == 200
    assert own_user != other_user


def test_transcript_read_back_is_masked(chat_client):
    token, session_id, _ = _customer_login(chat_client, CUSTOMER_USERNAME)
    _chat(
        chat_client,
        token,
        "我是王守成，身份证号110101198803150218，手机号13800138001，银行卡号6222021234567890",
    )

    internal = _internal_token(chat_client, ADVISOR_USERNAME)
    messages = _get_session(chat_client, internal, session_id).json()["data"]["messages"]
    user_content = next(message["content"] for message in messages if message["role"] == "user")

    assert "王守成" not in user_content
    assert "110101198803150218" not in user_content
    assert "13800138001" not in user_content
    assert "6222021234567890" not in user_content
