import json
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.settings import get_settings

CUSTOMER_USERNAME = "wangc1"
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
            # 见 test_customer_service_agent.py 的 chat_client：保证 GraphRAG
            # 融合在这些流式测试里稳定走空图谱降级，不与图谱测试的命名空间耦合。
            "neo4j_graph_namespace": "wealth_test_customer_service_agent_unused",
            # 关键词臂阈值在这里显式注入：「无关问题应兜底」这条断言要的是用例自己
            # 掌握的分界，不依赖 issue 04 校准出的默认值（它随语料漂移）。
            "retrieval_keyword_score_threshold": 10.0,
        }
    )
    app.dependency_overrides[get_settings] = lambda: test_settings
    try:
        yield auth_client
    finally:
        app.dependency_overrides.pop(get_settings, None)


def _customer_login(client: TestClient) -> str:
    response = client.post(
        "/api/customer/auth/login",
        json={"username": CUSTOMER_USERNAME, "password": SEEDED_PASSWORD},
    )
    return response.json()["data"]["access_token"]


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


def _parse_sse_frames(body: str) -> list[tuple[str, dict]]:
    frames = []
    for raw_frame in body.split("\n\n"):
        if not raw_frame.strip():
            continue
        event = "message"
        data = None
        for line in raw_frame.splitlines():
            if line.startswith("event:"):
                event = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data = json.loads(line.split(":", 1)[1].strip())
        assert data is not None
        frames.append((event, data))
    return frames


def test_stream_returns_event_stream_and_ends_with_full_fallback_answer(chat_client):
    token = _customer_login(chat_client)

    with chat_client.stream(
        "POST",
        "/api/customer/chat/stream",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": "阿尔法半人马座恒星系统的行星编号列表是什么"},
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        body = "".join(response.iter_text())

    frames = _parse_sse_frames(body)
    assert frames, "流式响应应至少包含一帧"

    *delta_frames, (last_event, last_data) = frames
    assert all(event == "message" for event, _ in delta_frames)
    assert last_event == "done"

    streamed_answer = "".join(data["delta"] for _, data in delta_frames)
    assert streamed_answer == last_data["answer"]
    assert last_data["citations"] == []
    assert "人工客服" in last_data["answer"] or "95588" in last_data["answer"]
    # done 帧是整个 ChatResponse 的 model_dump()：结果表这个字段在场（有行的数据查询
    # 才填它，其余分支与出口都是 None），字段本身不进事件名——客户侧 parseFrame 把
    # 无名事件当 delta 用，新事件名会在答案尾部追加 undefined（ADR-0028）。
    assert last_data["data_answer"] is None


def test_stream_ends_with_structured_citations_matching_uploaded_document(chat_client):
    chunk_text = "本产品的管理费率为百分之一点二每年，最短持有期为九十天。"
    upload_response = _upload(
        chat_client,
        filename="test_stream_citation.txt",
        content=chunk_text.encode("utf-8"),
        knowledge_type="产品",
    )
    knowledge_id = upload_response.json()["data"]["knowledge_id"]

    try:
        token = _customer_login(chat_client)

        with chat_client.stream(
            "POST",
            "/api/customer/chat/stream",
            headers={"Authorization": f"Bearer {token}"},
            json={"message": chunk_text},
        ) as response:
            body = "".join(response.iter_text())

        frames = _parse_sse_frames(body)
        _, last_data = frames[-1]

        assert last_data["citations"], "命中片段时流式响应也应携带结构化引用"
        citation = last_data["citations"][0]
        assert citation["knowledge_id"] == knowledge_id
        assert citation["source_file"] == "test_stream_citation.txt"
        assert chunk_text in last_data["answer"]
    finally:
        _delete(chat_client, knowledge_id)


def test_stream_requires_customer_authentication(chat_client):
    response = chat_client.post(
        "/api/customer/chat/stream",
        json={"message": "你好"},
    )
    assert response.status_code == 401


def test_stream_disconnecting_mid_stream_raises_no_uncaught_exception(chat_client, caplog):
    token = _customer_login(chat_client)

    with caplog.at_level("ERROR"):
        with chat_client.stream(
            "POST",
            "/api/customer/chat/stream",
            headers={"Authorization": f"Bearer {token}"},
            json={"message": "你好呀，今天天气不错"},
        ) as response:
            iterator = response.iter_bytes()
            next(iterator)

    assert not any(
        "unhandled error" in record.message or "SSE 推流中断" in record.message
        for record in caplog.records
    )

    # 服务在客户端提前断开后应保持正常，后续请求不受影响。
    follow_up = chat_client.post(
        "/api/customer/chat/messages",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": "你好呀"},
    )
    assert follow_up.status_code == 200
