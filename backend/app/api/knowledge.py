from datetime import datetime, timezone
from typing import cast

from fastapi import APIRouter, BackgroundTasks, Depends, Form, UploadFile
from sqlalchemy.orm import Session

from app.auth.dependencies import AuthContext, require_internal
from app.db.models import KnowledgeMeta
from app.db.session import get_session
from app.exceptions import AppError
from app.http import ok
from app.knowledge.rerank import rerank_chunks
from app.knowledge.schemas import (
    ChunkHitResponse,
    DocumentResponse,
    DocumentStatus,
    IngestStage,
    KnowledgeType,
    SearchRequest,
    SearchResponse,
)
from app.knowledge.service import (
    create_pending_document,
    delete_document,
    list_documents,
    process_ingestion,
    search_chunks,
)
from app.settings import Settings, get_settings

router = APIRouter(prefix="/api/internal/knowledge")


def _document_response(meta: KnowledgeMeta) -> dict:
    return DocumentResponse(
        knowledge_id=meta.id,
        knowledge_type=cast(KnowledgeType, meta.knowledge_type),
        title=meta.title,
        source_file=meta.source_file,
        version=meta.version,
        status=cast(DocumentStatus, meta.status),
        chunk_count=meta.chunk_count,
        expire_at=meta.expire_at,
        create_time=meta.create_time,
        stage=cast("IngestStage | None", meta.stage),
        failure_reason=meta.failure_reason,
    ).model_dump(mode="json")


@router.post("/documents")
def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile,
    knowledge_type: KnowledgeType = Form(...),
    title: str | None = Form(default=None),
    db: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    _auth: AuthContext = Depends(require_internal),
):
    if settings.demo_replay:
        # 入库会调用向量化、Milvus 与对象存储（ADR-0008：回放不发起外部调用），
        # 演示现场误触要得到明确的业务拒绝而不是一次悬着的外呼。
        raise AppError(400, "回放模式下知识库管理不可用")
    content = file.file.read()
    filename = file.filename or ""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    meta = create_pending_document(
        db, filename=filename, knowledge_type=knowledge_type, title=title, now=now
    )
    # `db` 是本次请求注入的 session，直接交给后台任务而不是另开一个：background_tasks
    # 在 yield 依赖的收尾代码之前执行，此时这个 session 还没被关闭。姊妹项目
    # app/api/customer/chat.py::_persist_turn 用的是同一个取舍。
    background_tasks.add_task(
        process_ingestion,
        db,
        settings,
        meta.id,
        filename=filename,
        content=content,
        knowledge_type=knowledge_type,
    )
    return ok(_document_response(meta))


@router.get("/documents")
def list_knowledge_documents(
    knowledge_type: KnowledgeType | None = None,
    status: str | None = None,
    db: Session = Depends(get_session),
    _auth: AuthContext = Depends(require_internal),
):
    metas = list_documents(db, knowledge_type=knowledge_type, status=status)
    return ok([_document_response(meta) for meta in metas])


@router.delete("/documents/{knowledge_id}")
def delete_knowledge_document(
    knowledge_id: int,
    db: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    _auth: AuthContext = Depends(require_internal),
):
    if settings.demo_replay:
        # 下架要触碰对象存储与 Milvus（同上传，ADR-0008）。
        raise AppError(400, "回放模式下知识库管理不可用")
    meta = delete_document(db, settings, knowledge_id)
    return ok(_document_response(meta))


@router.post("/search")
def search_knowledge(
    body: SearchRequest,
    db: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    _auth: AuthContext = Depends(require_internal),
):
    # 候选池按召回臂的宽度取，重排再决定最终返回几条——与聊天检索是同一条流水线、
    # 同一个排名（重排由调用方显式串，见 app/knowledge/rerank.py 的模块说明）。
    candidates = search_chunks(
        db,
        settings,
        query=body.query,
        knowledge_type=body.knowledge_type,
        top_k=settings.hybrid_recall_top_k,
    )
    results = rerank_chunks(
        body.query,
        candidates,
        settings,
        db=db,
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
        ],
        score_threshold=settings.retrieval_score_threshold,
    )
    return ok(response.model_dump())
