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


def _get_current(client: TestClient, token: str):
    return client.get(
        "/api/customer/conversations/current",
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

    # 只读回看：详情只给 role / content / citations / 时间 / data，内部与合规字段不外泄。
    # `data` 是数据回答那一轮的结果表（ADR-0028）——要送达客户得显式加一次，因此这条
    # 白名单断言刻意被改宽，改断言本身就是「这一步是刻意的」的记录。
    for message in messages:
        assert set(message.keys()) <= {
            "role",
            "content",
            "citations",
            "created_at",
            "data",
        }
    assert isinstance(messages[1]["citations"], list)
    # 这轮是闲聊，没有结果表：字段在、值为空。
    assert messages[1]["data"] is None


def test_customer_cannot_read_foreign_or_unknown_session(chat_client):
    token_a, sid_a, _ = _customer_login(chat_client, CUSTOMER_USERNAME)
    _chat(chat_client, token_a, "A 的提问")

    token_b, _, _ = _customer_login(chat_client, OTHER_CUSTOMER_USERNAME)

    # 别人的会话：即使拿到 session_id 也查不到（不暴露存在性）。
    assert _get_history(chat_client, token_b, sid_a).status_code == 404
    # 不存在的会话。
    assert _get_history(chat_client, token_b, "no-such-session").status_code == 404


def test_customer_reads_back_current_session_after_reload(chat_client):
    """刷新页面丢掉前端内存态后，这一场会话要能读回来。

    刷新不是重新登录：session_id 没变，因此刚才那两轮归档在「当前会话」名下——
    历史列表排除它（它还没结束），列表之外的这条读法负责把它补回对话框。
    """
    token, sid, _ = _customer_login(chat_client, CUSTOMER_USERNAME)
    _chat(chat_client, token, "刷新前的一句提问")

    current = _get_current(chat_client, token)
    assert current.status_code == 200
    data = current.json()["data"]
    assert data["session_id"] == sid

    messages = data["messages"]
    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert messages[0]["content"] == "刷新前的一句提问"
    # 与历史详情同一套客户可见字段，不多不少。
    for message in messages:
        assert set(message.keys()) <= {"role", "content", "citations", "created_at", "data"}
    assert isinstance(messages[1]["citations"], list)
    assert messages[1]["data"] is None

    # 同一场会话仍被历史列表排除：两条读法各管一段，不重叠。
    items = _list_history(chat_client, token).json()["data"]["items"]
    assert sid not in {item["session_id"] for item in items}


def test_current_session_is_empty_before_the_first_question(chat_client):
    """刚登录还没说过话：空列表，不是 404——「没有对话可补」是正常状态，不是错误。"""
    token, sid, _ = _customer_login(chat_client, CUSTOMER_USERNAME)

    current = _get_current(chat_client, token)
    assert current.status_code == 200
    data = current.json()["data"]
    assert data["session_id"] == sid
    assert data["messages"] == []


def test_current_session_is_scoped_to_the_credential(chat_client):
    """当前会话由凭证里的 session_id 决定：别的客户读自己的，读不到别人那一场。"""
    token_a, _, _ = _customer_login(chat_client, CUSTOMER_USERNAME)
    _chat(chat_client, token_a, "A 当前会话里的提问")

    token_b, sid_b, _ = _customer_login(chat_client, OTHER_CUSTOMER_USERNAME)
    current_b = _get_current(chat_client, token_b)
    assert current_b.status_code == 200
    data_b = current_b.json()["data"]
    assert data_b["session_id"] == sid_b
    # B 还没说过话：A 的那场不能漏过来。
    assert data_b["messages"] == []


def test_customer_history_endpoints_require_customer_identity(chat_client):
    # 未认证。
    assert chat_client.get("/api/customer/conversations").status_code == 401
    assert chat_client.get("/api/customer/conversations/current").status_code == 401

    # 内部员工凭证在客户端点上无效（身份域隔离，ADR-0009 护栏 2）。
    login = chat_client.post(
        "/api/internal/auth/login",
        json={"username": ADVISOR_USERNAME, "password": SEEDED_PASSWORD},
    )
    internal_token = login.json()["data"]["access_token"]
    for path in ("/api/customer/conversations", "/api/customer/conversations/current"):
        response = chat_client.get(path, headers={"Authorization": f"Bearer {internal_token}"})
        assert response.status_code == 403
