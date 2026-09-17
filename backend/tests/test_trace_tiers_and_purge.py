"""留痕分级与清理（Seam 1，ADR-0011）：审计级永久保存，调试级按显式时间基准清理。

清理函数的时间基准由参数传入，而不是在内部读系统时钟——于是可以直接断言「基准为
某时刻时，恰好这几条被删、那几条还在」，不必等待真实时间流逝或改动系统时钟。
"""

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

import app.agent.graph as agent_graph
from app.agent import debug_trace
from app.db.models import AgentDebugTrace, ConversationArchive
from app.db.session import get_session
from app.knowledge.service import ChunkResult
from app.llm.provider import GroundedAnswer
from app.main import app
from app.settings import get_settings

CUSTOMER_USERNAME = "wangc1"
EMPLOYEE_USERNAME = "advisor1"
SEEDED_PASSWORD = "Test@1234"
RETENTION_DAYS = 30


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _session():
    override = app.dependency_overrides[get_session]
    iterator = override()
    return iterator, next(iterator)


@pytest.fixture
def trace_client(auth_client: TestClient) -> Iterator[TestClient]:
    base_settings = get_settings()
    test_settings = base_settings.model_copy(
        update={
            "milvus_collection": base_settings.test_milvus_collection,
            "embedding_api_key": "",
            "llm_api_key": "",
            "debug_trace_retention_days": RETENTION_DAYS,
            # 与 test_customer_service_agent.py 同一理由：让 GraphRAG 融合稳定走
            # 「实体未命中」静默降级，不因别的测试模块重建过命名空间而耦合。
            "neo4j_graph_namespace": "wealth_test_customer_service_agent_unused",
        }
    )
    app.dependency_overrides[get_settings] = lambda: test_settings
    _clear_debug_traces()
    try:
        yield auth_client
    finally:
        _clear_debug_traces()
        app.dependency_overrides.pop(get_settings, None)


def _clear_debug_traces() -> None:
    iterator, session = _session()
    try:
        session.execute(delete(AgentDebugTrace))
        session.commit()
    finally:
        iterator.close()


def _add_debug_trace(*, trace_id: str, created_at: datetime) -> None:
    iterator, session = _session()
    try:
        session.add(
            AgentDebugTrace(
                trace_id=trace_id,
                session_id=f"session-{trace_id}",
                user_id=1,
                agent_type="customer_service",
                prompt=[{"role": "user", "content": "问题"}],
                retrieval_snippets=[],
                duration_ms=12,
                create_time=created_at,
            )
        )
        session.commit()
    finally:
        iterator.close()


def _debug_trace_ids() -> list[str]:
    iterator, session = _session()
    try:
        return list(
            session.scalars(select(AgentDebugTrace.trace_id).order_by(AgentDebugTrace.id))
        )
    finally:
        iterator.close()


def _internal_headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/internal/auth/login",
        json={"username": EMPLOYEE_USERNAME, "password": SEEDED_PASSWORD},
    )
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


def _customer_login(client: TestClient) -> tuple[str, str]:
    response = client.post(
        "/api/customer/auth/login",
        json={"username": CUSTOMER_USERNAME, "password": SEEDED_PASSWORD},
    )
    token = response.json()["data"]["access_token"]
    session_id = pyjwt.decode(token, options={"verify_signature": False})["sid"]
    return token, session_id


def _chat(client: TestClient, token: str, message: str):
    return client.post(
        "/api/customer/chat/messages",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": message},
    )


def _purge(client: TestClient):
    return client.post("/api/internal/traces/purge", headers=_internal_headers(client))


def test_purge_deletes_only_debug_traces_beyond_retention(trace_client):
    now = _utcnow()
    _add_debug_trace(trace_id="debug-old", created_at=now - timedelta(days=RETENTION_DAYS + 10))
    _add_debug_trace(trace_id="debug-recent", created_at=now - timedelta(days=10))

    audit_session_id = "purge-audit-session"
    iterator, session = _session()
    try:
        session.add(
            ConversationArchive(
                session_id=audit_session_id,
                identity_domain="customer",
                user_id=1,
                agent_type="customer_service",
                role="user",
                content="很久以前的会话",
                create_time=now - timedelta(days=365),
            )
        )
        session.commit()

        deleted = debug_trace.purge(session, now=now, retention_days=RETENTION_DAYS)

        assert deleted == 1
        assert _debug_trace_ids() == ["debug-recent"]
        # 审计级留痕不受任何清理影响，哪怕它比保留期老得多。
        remaining_audit = session.scalar(
            select(func.count())
            .select_from(ConversationArchive)
            .where(ConversationArchive.session_id == audit_session_id)
        )
        assert remaining_audit == 1
    finally:
        session.execute(
            delete(ConversationArchive).where(ConversationArchive.session_id == audit_session_id)
        )
        session.commit()
        iterator.close()


def test_purge_uses_the_passed_basis_not_the_wall_clock(trace_client):
    # 这条记录按真实时钟还很新；若清理函数内部读时钟就不会删它。
    _add_debug_trace(trace_id="debug-just-now", created_at=_utcnow() - timedelta(hours=1))

    iterator, session = _session()
    try:
        future = _utcnow() + timedelta(days=365)
        deleted = debug_trace.purge(session, now=future, retention_days=RETENTION_DAYS)
        assert deleted == 1
    finally:
        iterator.close()


def test_purge_with_the_same_basis_is_idempotent(trace_client):
    now = _utcnow()
    _add_debug_trace(trace_id="debug-old", created_at=now - timedelta(days=RETENTION_DAYS + 1))

    iterator, session = _session()
    try:
        assert debug_trace.purge(session, now=now, retention_days=RETENTION_DAYS) == 1
        assert debug_trace.purge(session, now=now, retention_days=RETENTION_DAYS) == 0
    finally:
        iterator.close()


def test_purge_endpoint_requires_internal_identity(trace_client):
    assert trace_client.post("/api/internal/traces/purge").status_code == 401


def test_purge_endpoint_removes_expired_debug_traces_and_reports_the_run(trace_client):
    now = _utcnow()
    _add_debug_trace(trace_id="debug-old", created_at=now - timedelta(days=RETENTION_DAYS + 5))
    _add_debug_trace(trace_id="debug-recent", created_at=now - timedelta(days=1))

    response = _purge(trace_client)

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["deleted"] == 1
    assert data["retention_days"] == RETENTION_DAYS
    assert data["basis"]
    assert _debug_trace_ids() == ["debug-recent"]


def test_chat_turn_records_debug_trace_alongside_audit_archive(trace_client, monkeypatch):
    snippet = ChunkResult(
        knowledge_id=7777,
        knowledge_type="FAQ",
        chunk_index=0,
        heading_path=["产品要素"],
        content="本产品最短持有期为九十天。",
        score=0.99,
        title="产品要素说明",
        source_file="stub-faq.txt",
    )
    monkeypatch.setattr(agent_graph, "search_chunks", lambda *args, **kwargs: [snippet])
    monkeypatch.setattr(
        agent_graph,
        "generate_grounded_answer",
        lambda question, history, chunks, settings: GroundedAnswer(
            text=f"{chunks[0].content}[1]", cited_chunk_numbers=[1]
        ),
    )

    token, session_id = _customer_login(trace_client)
    response = _chat(trace_client, token, "这个产品的期限是多久")
    assert response.status_code == 200

    iterator, session = _session()
    try:
        row = session.scalar(
            select(AgentDebugTrace).where(AgentDebugTrace.session_id == session_id)
        )
        assert row is not None
        assert row.agent_type == "customer_service"
        assert row.trace_id
        prompt_text = " ".join(
            message["content"] for message in (row.prompt or [])
        )
        assert snippet.content in prompt_text
        assert (row.retrieval_snippets or [])[0]["content"] == snippet.content
        assert row.duration_ms is not None and row.duration_ms >= 0

        # 同一回合在审计级留痕里也留下了使用者、问题、答案与引用。
        archived = session.scalar(
            select(func.count())
            .select_from(ConversationArchive)
            .where(ConversationArchive.session_id == session_id)
        )
        assert archived == 2
    finally:
        session.execute(
            delete(ConversationArchive).where(ConversationArchive.session_id == session_id)
        )
        session.commit()
        iterator.close()
