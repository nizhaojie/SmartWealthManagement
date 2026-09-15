from typing import cast

from fastapi import APIRouter, Depends, Form, UploadFile
from sqlalchemy.orm import Session

from app.auth.dependencies import AuthContext, require_internal
from app.db.models import KnowledgeMeta
from app.db.session import get_session
from app.http import ok
from app.knowledge.schemas import (
    ChunkHitResponse,
    DocumentResponse,
    KnowledgeType,
    SearchRequest,
    SearchResponse,
)
from app.knowledge.service import delete_document, ingest_document, search_chunks
from app.settings import Settings, get_settings

router = APIRouter(prefix="/api/internal/knowledge")


def _document_response(meta: KnowledgeMeta) -> dict:
    return DocumentResponse(
        knowledge_id=meta.id,
        title=meta.title,
        knowledge_type=cast(KnowledgeType, meta.knowledge_type),
        status=meta.status,
        chunk_count=meta.chunk_count,
    ).model_dump()


@router.post("/documents")
def upload_document(
    file: UploadFile,
    knowledge_type: KnowledgeType = Form(...),
    title: str | None = Form(default=None),
    db: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    _auth: AuthContext = Depends(require_internal),
):
    content = file.file.read()
    meta = ingest_document(
        db,
        settings,
        filename=file.filename or "",
        content=content,
        knowledge_type=knowledge_type,
        title=title,
    )
    return ok(_document_response(meta))


@router.delete("/documents/{knowledge_id}")
def delete_knowledge_document(
    knowledge_id: int,
    db: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    _auth: AuthContext = Depends(require_internal),
):
    meta = delete_document(db, settings, knowledge_id)
    return ok(_document_response(meta))


@router.post("/search")
def search_knowledge(
    body: SearchRequest,
    db: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    _auth: AuthContext = Depends(require_internal),
):
    results = search_chunks(
        db,
        settings,
        query=body.query,
        knowledge_type=body.knowledge_type,
        top_k=body.top_k,
    )
    response = SearchResponse(
        hits=[
            ChunkHitResponse(
                knowledge_id=result.knowledge_id,
                knowledge_type=cast(KnowledgeType, result.knowledge_type),
                chunk_index=result.chunk_index,
                heading_path=result.heading_path,
                content=result.content,
                score=result.score,
                title=result.title,
                source_file=result.source_file,
            )
            for result in results
        ]
    )
    return ok(response.model_dump())
