"""Seam 1：图谱重建的管理接口——触发、统计、并发互斥、未授权拒绝。"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.db.models import GraphSyncRun
from app.db.session import get_session
from app.main import app
from app.settings import get_settings

EMPLOYEE_USERNAME = "advisor1"
SEEDED_PASSWORD = "Test@1234"


@pytest.fixture
def graph_client(auth_client: TestClient) -> Iterator[TestClient]:
    base_settings = get_settings()
    test_settings = base_settings.model_copy(
        update={"neo4j_graph_namespace": base_settings.test_neo4j_graph_namespace}
    )
    app.dependency_overrides[get_settings] = lambda: test_settings
    try:
        yield auth_client
    finally:
        app.dependency_overrides.pop(get_settings, None)


def _internal_token(client: TestClient) -> str:
    response = client.post(
        "/api/internal/auth/login",
        json={"username": EMPLOYEE_USERNAME, "password": SEEDED_PASSWORD},
    )
    return response.json()["data"]["access_token"]


def _auth_headers(client: TestClient) -> dict[str, str]:
    return {"Authorization": f"Bearer {_internal_token(client)}"}


def _clear_sync_runs(client: TestClient) -> None:
    override = app.dependency_overrides[get_session]
    session_iter = override()
    session = next(session_iter)
    try:
        session.execute(delete(GraphSyncRun))
        session.commit()
    finally:
        session_iter.close()


def test_rebuild_requires_auth(graph_client):
    response = graph_client.post("/api/internal/graph/rebuild")
    assert response.status_code == 401


def test_rebuild_then_stats_reflects_result(graph_client):
    _clear_sync_runs(graph_client)

    response = graph_client.post(
        "/api/internal/graph/rebuild", headers=_auth_headers(graph_client)
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["running"] is False
    assert data["last_attempt_status"] == "成功"
    assert data["node_count"] > 0
    assert data["relationship_count"] > 0
    assert data["synced_at"] is not None
    assert data["duration_ms"] >= 0

    stats_response = graph_client.get(
        "/api/internal/graph/stats", headers=_auth_headers(graph_client)
    )
    assert stats_response.status_code == 200
    stats = stats_response.json()["data"]
    assert stats["node_count"] == data["node_count"]
    assert stats["relationship_count"] == data["relationship_count"]
    assert stats["synced_at"] == data["synced_at"]


def test_stats_before_any_rebuild_reports_never_synced(graph_client):
    _clear_sync_runs(graph_client)

    response = graph_client.get("/api/internal/graph/stats", headers=_auth_headers(graph_client))

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["running"] is False
    assert data["node_count"] is None
    assert data["relationship_count"] is None
    assert data["synced_at"] is None
    assert data["last_attempt_status"] is None


def test_concurrent_rebuild_is_rejected_with_409(graph_client):
    _clear_sync_runs(graph_client)
    override = app.dependency_overrides[get_session]
    session_iter = override()
    session = next(session_iter)
    try:
        from datetime import datetime, timezone

        session.add(
            GraphSyncRun(
                lock_key="running",
                status="进行中",
                started_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
        )
        session.commit()
    finally:
        session_iter.close()

    response = graph_client.post(
        "/api/internal/graph/rebuild", headers=_auth_headers(graph_client)
    )

    assert response.status_code == 409
    body = response.json()
    assert "重建正在进行中" in body["message"]

    _clear_sync_runs(graph_client)
