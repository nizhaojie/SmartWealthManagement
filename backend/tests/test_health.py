from pathlib import Path

from app.settings import get_settings

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"


def test_health_returns_unified_envelope(client):
    response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 200
    assert body["message"] == "success"
    assert "data" in body
    assert isinstance(body["trace_id"], str) and body["trace_id"]


def test_health_reports_dependency_connectivity(client):
    body = client.get("/api/health").json()
    dependencies = body["data"]["dependencies"]

    for name in ("mysql", "redis", "etcd", "minio", "milvus", "neo4j"):
        assert name in dependencies
        assert dependencies[name]["ok"] in (True, False)

    assert body["data"]["status"] in ("ok", "degraded")
    if all(item["ok"] for item in dependencies.values()):
        assert body["data"]["status"] == "ok"
    else:
        assert body["data"]["status"] == "degraded"


def test_health_uses_fake_provider_when_llm_key_missing(client, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "")
    get_settings.cache_clear()
    try:
        body = client.get("/api/health").json()
        assert body["data"]["llm_provider"] == "fake"
    finally:
        get_settings.cache_clear()


def test_swagger_docs_are_available(client):
    response = client.get("/docs")
    assert response.status_code == 200
    assert "swagger" in response.text.lower()


def test_validation_error_is_wrapped_without_stack(client):
    response = client.post("/api/__test__/validate", json={})
    body = response.json()
    assert response.status_code == 400
    assert body["code"] == 400
    assert body["trace_id"]
    assert "Traceback" not in response.text


def test_business_error_is_wrapped_without_stack(client):
    response = client.get("/api/__test__/business-error")
    body = response.json()
    assert body["code"] == 1002
    assert body["message"] == "知识库检索无结果"
    assert body["trace_id"]
    assert "Traceback" not in response.text


def test_system_error_is_wrapped_without_stack(client):
    response = client.get("/api/__test__/system-error")
    body = response.json()
    assert response.status_code == 500
    assert body["code"] == 500
    assert body["trace_id"]
    assert "Traceback" not in response.text
    assert "secret stack boom" not in response.text


def test_trace_id_is_on_every_json_response(client):
    health = client.get("/api/health").json()
    missing = client.get("/api/does-not-exist").json()
    assert health["trace_id"]
    assert missing["trace_id"]
    assert missing["code"] == 404


def test_trace_id_appears_in_request_log_lines(client):
    response = client.get("/api/health")
    trace_id = response.json()["trace_id"]
    info_log = (LOG_DIR / "info.log").read_text(encoding="utf-8")
    assert any(
        trace_id in line and "/api/health" in line
        for line in info_log.splitlines()
    )


def test_error_log_contains_only_error_lines_with_trace_id(client):
    response = client.get("/api/__test__/system-error")
    trace_id = response.json()["trace_id"]
    error_log = (LOG_DIR / "error.log").read_text(encoding="utf-8")
    info_log = (LOG_DIR / "info.log").read_text(encoding="utf-8")
    assert any(trace_id in line and "ERROR" in line for line in error_log.splitlines())
    assert any(trace_id in line and "INFO" in line for line in info_log.splitlines())
    assert not any(trace_id in line and "ERROR" in line for line in info_log.splitlines())
    assert not any(trace_id in line and "INFO" in line for line in error_log.splitlines())
