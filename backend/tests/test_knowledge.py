import io
from collections.abc import Iterator

import pytest
from docx import Document as DocxDocument
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session as OrmSession

from app.db.models import KnowledgeMeta
from app.knowledge.seed_faq import FAQ_SOURCE_FILE, seed_faq
from app.main import app
from app.settings import get_settings

EMPLOYEE_USERNAME = "advisor1"
SEEDED_PASSWORD = "Test@1234"


@pytest.fixture
def knowledge_client(auth_client: TestClient) -> Iterator[TestClient]:
    base_settings = get_settings()
    test_settings = base_settings.model_copy(
        update={
            "milvus_collection": base_settings.test_milvus_collection,
            "embedding_api_key": "",
        }
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


def _upload(
    client: TestClient,
    *,
    filename: str,
    content: bytes,
    knowledge_type: str = "FAQ",
    content_type: str = "text/plain",
):
    return client.post(
        "/api/internal/knowledge/documents",
        headers=_auth_headers(client),
        files={"file": (filename, content, content_type)},
        data={"knowledge_type": knowledge_type},
    )


def _search(client: TestClient, *, query: str, knowledge_type: str | None = None, top_k: int = 5):
    body = {"query": query, "top_k": top_k}
    if knowledge_type is not None:
        body["knowledge_type"] = knowledge_type
    return client.post(
        "/api/internal/knowledge/search", headers=_auth_headers(client), json=body
    )


def _delete(client: TestClient, knowledge_id: int):
    return client.delete(
        f"/api/internal/knowledge/documents/{knowledge_id}", headers=_auth_headers(client)
    )


def test_upload_rejects_unsupported_format_with_business_error(knowledge_client):
    response = _upload(
        knowledge_client,
        filename="policy.pdf",
        content=b"%PDF-1.4 fake content",
        content_type="application/pdf",
    )

    assert response.status_code != 500
    body = response.json()
    assert body["code"] == 1006
    assert "格式" in body["message"]


def test_upload_txt_document_creates_active_record(knowledge_client):
    response = _upload(
        knowledge_client,
        filename="test_upload_txt.txt",
        content="随存随取型现金管理产品的赎回到账时间通常为下一个交易日。".encode("utf-8"),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "active"
    assert data["chunk_count"] >= 1
    assert data["knowledge_type"] == "FAQ"

    _delete(knowledge_client, data["knowledge_id"])


def test_uploaded_document_is_retrievable_by_exact_chunk_text(knowledge_client):
    chunk_text = "随存随取型现金管理产品的赎回到账时间通常为下一个交易日。"
    upload_response = _upload(
        knowledge_client, filename="test_retrieve_exact.txt", content=chunk_text.encode("utf-8")
    )
    knowledge_id = upload_response.json()["data"]["knowledge_id"]

    try:
        search_response = _search(knowledge_client, query=chunk_text)
        assert search_response.status_code == 200
        hits = search_response.json()["data"]["hits"]
        assert any(hit["knowledge_id"] == knowledge_id for hit in hits)
        matched = next(hit for hit in hits if hit["knowledge_id"] == knowledge_id)
        assert matched["content"] == chunk_text
        assert matched["source_file"] == "test_retrieve_exact.txt"
        assert matched["chunk_index"] == 0
        assert isinstance(matched["score"], float)
    finally:
        _delete(knowledge_client, knowledge_id)


def test_deleted_document_no_longer_appears_in_search_results(knowledge_client):
    chunk_text = "客户密码连续输错五次后账号将被临时锁定二十四小时。"
    upload_response = _upload(
        knowledge_client, filename="test_delete_then_search.txt", content=chunk_text.encode("utf-8")
    )
    knowledge_id = upload_response.json()["data"]["knowledge_id"]

    delete_response = _delete(knowledge_client, knowledge_id)
    assert delete_response.status_code == 200
    assert delete_response.json()["data"]["status"] == "expired"

    search_response = _search(knowledge_client, query=chunk_text)
    hits = search_response.json()["data"]["hits"]
    assert all(hit["knowledge_id"] != knowledge_id for hit in hits)


def test_deleting_unknown_document_returns_not_found(knowledge_client):
    response = _delete(knowledge_client, 999_999_999)
    assert response.status_code == 404


def test_markdown_heading_hierarchy_is_kept_as_chunk_metadata(knowledge_client):
    markdown = (
        "# 产品手册\n"
        "## 费率说明\n"
        "本产品的管理费率为百分之一点二每年，托管费率为百分之零点二每年。\n"
    )
    upload_response = _upload(
        knowledge_client,
        filename="test_markdown_heading.md",
        content=markdown.encode("utf-8"),
        knowledge_type="产品",
        content_type="text/markdown",
    )
    knowledge_id = upload_response.json()["data"]["knowledge_id"]

    try:
        search_response = _search(
            knowledge_client, query="本产品的管理费率为百分之一点二每年，托管费率为百分之零点二每年。"
        )
        hits = search_response.json()["data"]["hits"]
        matched = next(hit for hit in hits if hit["knowledge_id"] == knowledge_id)
        assert matched["heading_path"] == ["产品手册", "费率说明"]
    finally:
        _delete(knowledge_client, knowledge_id)


def test_docx_document_can_be_parsed_and_retrieved(knowledge_client):
    document = DocxDocument()
    document.add_heading("开户须知", level=1)
    document.add_paragraph("客户开户需提供本人身份证原件与银行卡，全程在网点办理。")
    buffer = io.BytesIO()
    document.save(buffer)

    upload_response = _upload(
        knowledge_client,
        filename="test_open_account.docx",
        content=buffer.getvalue(),
        knowledge_type="政策",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    assert upload_response.status_code == 200
    knowledge_id = upload_response.json()["data"]["knowledge_id"]

    try:
        search_response = _search(
            knowledge_client, query="客户开户需提供本人身份证原件与银行卡，全程在网点办理。"
        )
        hits = search_response.json()["data"]["hits"]
        matched = next(hit for hit in hits if hit["knowledge_id"] == knowledge_id)
        assert matched["heading_path"] == ["开户须知"]
    finally:
        _delete(knowledge_client, knowledge_id)


def test_search_can_be_scoped_to_a_knowledge_type(knowledge_client):
    faq_text = "客户经理更换流程需通过客服热线提交申请，三个工作日内完成。"
    policy_text = "客户经理更换事项适用公司内部人事调配政策的相关规定。"

    faq_upload = _upload(
        knowledge_client, filename="test_scope_faq.txt", content=faq_text.encode("utf-8"), knowledge_type="FAQ"
    )
    policy_upload = _upload(
        knowledge_client,
        filename="test_scope_policy.txt",
        content=policy_text.encode("utf-8"),
        knowledge_type="政策",
    )
    faq_id = faq_upload.json()["data"]["knowledge_id"]
    policy_id = policy_upload.json()["data"]["knowledge_id"]

    try:
        response = _search(knowledge_client, query=faq_text, knowledge_type="政策")
        hits = response.json()["data"]["hits"]
        assert all(hit["knowledge_id"] != faq_id for hit in hits)
    finally:
        _delete(knowledge_client, faq_id)
        _delete(knowledge_client, policy_id)


def test_faq_seed_imports_40_entries_and_they_are_retrievable(knowledge_client):
    base_settings = get_settings()
    seed_settings = base_settings.model_copy(
        update={
            "database_url": base_settings.test_database_url,
            "milvus_collection": base_settings.test_milvus_collection,
            "embedding_api_key": "",
        }
    )
    seed_faq(seed_settings)

    engine = create_engine(base_settings.test_database_url)
    try:
        with OrmSession(engine) as session:
            meta = session.scalar(
                select(KnowledgeMeta).where(KnowledgeMeta.source_file == FAQ_SOURCE_FILE)
            )
    finally:
        engine.dispose()

    assert meta is not None
    assert meta.status == "active"
    assert meta.chunk_count == 40

    response = _search(
        knowledge_client,
        query="密码连续输错五次后账号将被临时锁定二十四小时，此举用于防止密码被暴力破解。",
        knowledge_type="FAQ",
    )
    hits = response.json()["data"]["hits"]
    assert any(hit["knowledge_id"] == meta.id for hit in hits)


def test_fake_embedding_is_deterministic_across_repeated_searches(knowledge_client):
    chunk_text = "本产品最短持有期为九十天，提前赎回将收取百分之零点五的短期赎回费。"
    upload_response = _upload(
        knowledge_client, filename="test_determinism.txt", content=chunk_text.encode("utf-8")
    )
    knowledge_id = upload_response.json()["data"]["knowledge_id"]

    try:
        first = _search(knowledge_client, query=chunk_text).json()["data"]["hits"]
        second = _search(knowledge_client, query=chunk_text).json()["data"]["hits"]
        first_score = next(hit["score"] for hit in first if hit["knowledge_id"] == knowledge_id)
        second_score = next(hit["score"] for hit in second if hit["knowledge_id"] == knowledge_id)
        assert first_score == second_score
    finally:
        _delete(knowledge_client, knowledge_id)
