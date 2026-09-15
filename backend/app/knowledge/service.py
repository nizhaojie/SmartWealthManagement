from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import KnowledgeMeta
from app.exceptions import AppError
from app.knowledge import object_store, vector_store
from app.knowledge.embeddings import embed_texts
from app.knowledge.parsers import Section, is_supported, parse_document
from app.knowledge.tokenizer import chunk_text
from app.settings import Settings

UNSUPPORTED_FORMAT_CODE = 1006
UNSUPPORTED_FORMAT_MESSAGE = "不支持的文档格式，仅支持 txt / md / docx"
DOCUMENT_NOT_FOUND_MESSAGE = "知识文档不存在"

CHUNK_SIZE = 512
CHUNK_OVERLAP = 64

STATUS_ACTIVE = "active"
STATUS_EXPIRED = "expired"


@dataclass
class ChunkPiece:
    heading_path: list[str]
    text: str


@dataclass
class ChunkResult:
    knowledge_id: int
    knowledge_type: str
    chunk_index: int
    heading_path: list[str]
    content: str
    score: float
    title: str
    source_file: str


def ingest_document(
    db: Session,
    settings: Settings,
    *,
    filename: str,
    content: bytes,
    knowledge_type: str,
    title: str | None = None,
) -> KnowledgeMeta:
    if not is_supported(filename):
        raise AppError(UNSUPPORTED_FORMAT_CODE, UNSUPPORTED_FORMAT_MESSAGE)

    sections = parse_document(filename, content)
    pieces = _chunk_sections(sections)
    vectors = embed_texts([piece.text for piece in pieces], settings) if pieces else []

    meta = KnowledgeMeta(
        knowledge_type=knowledge_type,
        title=title or filename,
        source_file=filename,
        version="1",
        status=STATUS_ACTIVE,
        chunk_count=len(pieces),
    )
    db.add(meta)
    db.flush()

    minio_client = object_store.get_client(settings)
    milvus_client = vector_store.get_client(settings)
    key = object_store.object_key(meta.id, filename)
    try:
        object_store.upload(minio_client, settings.minio_bucket, key, content)
        vector_store.ensure_collection(
            milvus_client, settings.milvus_collection, settings.embedding_dimension
        )
        vector_store.insert_chunks(
            milvus_client,
            settings.milvus_collection,
            [
                vector_store.ChunkRecord(
                    knowledge_id=meta.id,
                    knowledge_type=knowledge_type,
                    chunk_index=index,
                    heading_path=piece.heading_path,
                    content=piece.text,
                    vector=vector,
                )
                for index, (piece, vector) in enumerate(zip(pieces, vectors))
            ],
        )
    except Exception:
        object_store.delete_if_exists(minio_client, settings.minio_bucket, key)
        vector_store.delete_by_knowledge_id(milvus_client, settings.milvus_collection, meta.id)
        db.rollback()
        raise

    meta.minio_path = key
    meta.milvus_collection = settings.milvus_collection
    db.commit()
    db.refresh(meta)
    return meta


def delete_document(db: Session, settings: Settings, knowledge_id: int) -> KnowledgeMeta:
    meta = db.get(KnowledgeMeta, knowledge_id)
    if meta is None or meta.status == STATUS_EXPIRED:
        raise AppError(404, DOCUMENT_NOT_FOUND_MESSAGE)

    milvus_client = vector_store.get_client(settings)
    vector_store.delete_by_knowledge_id(milvus_client, settings.milvus_collection, knowledge_id)

    if meta.minio_path:
        minio_client = object_store.get_client(settings)
        object_store.archive(minio_client, settings.minio_bucket, meta.minio_path)

    meta.status = STATUS_EXPIRED
    meta.expire_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    db.refresh(meta)
    return meta


def search_chunks(
    db: Session,
    settings: Settings,
    *,
    query: str,
    knowledge_type: str | None = None,
    top_k: int = 5,
) -> list[ChunkResult]:
    milvus_client = vector_store.get_client(settings)
    query_vector = embed_texts([query], settings)[0]
    hits = vector_store.search(
        milvus_client,
        settings.milvus_collection,
        query_vector=query_vector,
        top_k=top_k,
        knowledge_type=knowledge_type,
    )
    if not hits:
        return []

    knowledge_ids = {hit["knowledge_id"] for hit in hits}
    metas = {
        meta.id: meta
        for meta in db.scalars(select(KnowledgeMeta).where(KnowledgeMeta.id.in_(knowledge_ids)))
    }

    results: list[ChunkResult] = []
    for hit in hits:
        meta = metas.get(hit["knowledge_id"])
        if meta is None or meta.status != STATUS_ACTIVE:
            continue
        results.append(
            ChunkResult(
                knowledge_id=hit["knowledge_id"],
                knowledge_type=hit["knowledge_type"],
                chunk_index=hit["chunk_index"],
                heading_path=hit["heading_path"],
                content=hit["content"],
                score=hit["score"],
                title=meta.title,
                source_file=meta.source_file,
            )
        )
    return results


def _chunk_sections(sections: list[Section]) -> list[ChunkPiece]:
    pieces: list[ChunkPiece] = []
    for section in sections:
        for text in chunk_text(section.text, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
            pieces.append(ChunkPiece(heading_path=section.heading_path, text=text))
    return pieces
