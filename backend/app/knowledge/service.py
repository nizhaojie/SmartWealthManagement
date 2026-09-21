import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal, TypeVar

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from app import degradation
from app.db.models import KnowledgeChunk, KnowledgeMeta
from app.exceptions import AppError
from app.knowledge import object_store, vector_store
from app.knowledge.embeddings import embed_texts
from app.knowledge.parsers import Section, is_supported, parse_document
from app.knowledge.tokenizer import chunk_text
from app.replay import library as replay_library
from app.settings import Settings
from app.tracing import get_trace_id

logger = logging.getLogger("app.knowledge")

UNSUPPORTED_FORMAT_CODE = 1006
UNSUPPORTED_FORMAT_MESSAGE = "不支持的文档格式，仅支持 txt / md / docx"
DOCUMENT_NOT_FOUND_MESSAGE = "知识文档不存在"
INGESTION_FAILED_CODE = 1008

# 检索降级原因（进 `biz_degradation_trace` 的 reason 列）。
DEGRADED_VECTOR_TIMEOUT = degradation.REASON_TIMEOUT
DEGRADED_VECTOR_UNAVAILABLE = degradation.REASON_UNAVAILABLE

# 关键词兜底最多扫多少行候选：LIKE 命中面可能很宽，先截断再在 Python 里精排，
# 避免一次抖动把整张分块表拉进内存。
KEYWORD_SCAN_LIMIT = 500

CHUNK_SIZE = 512
CHUNK_OVERLAP = 64

STATUS_PROCESSING = "processing"
STATUS_ACTIVE = "active"
STATUS_FAILED = "failed"
STATUS_EXPIRED = "expired"

STAGE_PARSE = "parse"
STAGE_CHUNK = "chunk"
STAGE_EMBED = "embed"
STAGE_STORE = "store"

# 需求文档 2278 行：政策法规类默认有效期 1 年，产品说明默认半年；FAQ 未提及默认值，留空表示不设期限。
DEFAULT_EXPIRY_DAYS: dict[str, int] = {
    "政策": 365,
    "产品": 180,
}


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
    # 结果来源：向量检索固定是 "vector"；图谱查询产出的段落用 "graph" 构造同类型
    # 对象，以便和向量结果一起排序；向量不可用降级为关键词检索时标 "keyword"。
    # 三种来源的打分不是同一量纲（余弦相似度 / 命中字词占比），兜底判定据此分设阈值。
    source: Literal["vector", "graph", "keyword"] = "vector"


def create_pending_document(
    db: Session,
    *,
    filename: str,
    knowledge_type: str,
    now: datetime,
    title: str | None = None,
) -> KnowledgeMeta:
    if not is_supported(filename):
        raise AppError(UNSUPPORTED_FORMAT_CODE, UNSUPPORTED_FORMAT_MESSAGE)

    expire_after_days = DEFAULT_EXPIRY_DAYS.get(knowledge_type)
    meta = KnowledgeMeta(
        knowledge_type=knowledge_type,
        title=title or filename,
        source_file=filename,
        version="1",
        status=STATUS_PROCESSING,
        chunk_count=0,
        expire_at=now + timedelta(days=expire_after_days) if expire_after_days else None,
    )
    db.add(meta)
    db.commit()
    db.refresh(meta)
    return meta


def _mark_failed(db: Session, meta: KnowledgeMeta, stage: str, reason: str) -> None:
    meta.status = STATUS_FAILED
    meta.stage = stage
    meta.failure_reason = reason[:1000]
    db.commit()


class _StageFailed(Exception):
    """Internal control-flow signal: a stage already recorded its own failure."""


_T = TypeVar("_T")


def _run_stage(db: Session, meta: KnowledgeMeta, stage: str, fn: Callable[[], _T]) -> _T:
    meta.stage = stage
    db.commit()
    try:
        return fn()
    except Exception as exc:
        _mark_failed(db, meta, stage, str(exc))
        raise _StageFailed from exc


def _run_ingestion_pipeline(
    db: Session,
    settings: Settings,
    meta: KnowledgeMeta,
    *,
    filename: str,
    content: bytes,
    knowledge_type: str,
) -> None:
    try:
        sections = _run_stage(db, meta, STAGE_PARSE, lambda: parse_document(filename, content))
        pieces = _run_stage(db, meta, STAGE_CHUNK, lambda: _chunk_sections(sections))
        vectors = _run_stage(
            db,
            meta,
            STAGE_EMBED,
            lambda: embed_texts([piece.text for piece in pieces], settings) if pieces else [],
        )
    except _StageFailed:
        return

    meta.stage = STAGE_STORE
    meta.chunk_count = len(pieces)
    db.commit()

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
        _replace_chunk_mirror(db, meta, pieces, knowledge_type)
    except Exception as exc:
        object_store.delete_if_exists(minio_client, settings.minio_bucket, key)
        vector_store.delete_by_knowledge_id(milvus_client, settings.milvus_collection, meta.id)
        _replace_chunk_mirror(db, meta, [], knowledge_type)
        _mark_failed(db, meta, STAGE_STORE, str(exc))
        return

    meta.minio_path = key
    meta.milvus_collection = settings.milvus_collection
    meta.status = STATUS_ACTIVE
    meta.stage = None
    db.commit()


def process_ingestion(
    db: Session,
    settings: Settings,
    knowledge_id: int,
    *,
    filename: str,
    content: bytes,
    knowledge_type: str,
) -> None:
    meta = db.get(KnowledgeMeta, knowledge_id)
    if meta is None:
        return
    _run_ingestion_pipeline(
        db, settings, meta, filename=filename, content=content, knowledge_type=knowledge_type
    )


def ingest_document(
    db: Session,
    settings: Settings,
    *,
    filename: str,
    content: bytes,
    knowledge_type: str,
    title: str | None = None,
) -> KnowledgeMeta:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    meta = create_pending_document(
        db, filename=filename, knowledge_type=knowledge_type, title=title, now=now
    )
    _run_ingestion_pipeline(
        db, settings, meta, filename=filename, content=content, knowledge_type=knowledge_type
    )
    if meta.status == STATUS_FAILED:
        raise AppError(INGESTION_FAILED_CODE, meta.failure_reason or "知识入库处理失败")
    return meta


def list_documents(
    db: Session,
    *,
    knowledge_type: str | None = None,
    status: str | None = None,
) -> list[KnowledgeMeta]:
    stmt = select(KnowledgeMeta).order_by(KnowledgeMeta.create_time.desc())
    if knowledge_type:
        stmt = stmt.where(KnowledgeMeta.knowledge_type == knowledge_type)
    if status:
        stmt = stmt.where(KnowledgeMeta.status == status)
    else:
        # 删除后文档要从列表消失（ticket 02），但状态筛选里仍然保留 expired
        # 选项供维护者按需查——所以只在没有显式按状态筛选时默认排掉它。
        stmt = stmt.where(KnowledgeMeta.status != STATUS_EXPIRED)
    return list(db.scalars(stmt))


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


def _replace_chunk_mirror(
    db: Session,
    meta: KnowledgeMeta,
    pieces: list[ChunkPiece],
    knowledge_type: str,
) -> None:
    """把分块正文同步到 MySQL 镜像表（覆盖式）。

    镜像的唯一用途是「向量库不可用时还有一条检索路径」，因此它跟着 Milvus 的写入
    一起成功或一起失败：入库事务里 `pieces` 为空表示回滚，把已经写进去的镜像行删掉。
    """
    db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.knowledge_id == meta.id))
    db.add_all(
        [
            KnowledgeChunk(
                knowledge_id=meta.id,
                knowledge_type=knowledge_type,
                chunk_index=index,
                heading_path=piece.heading_path,
                content=piece.text,
            )
            for index, piece in enumerate(pieces)
        ]
    )
    db.commit()


def _vector_search_hits(
    settings: Settings, *, query: str, knowledge_type: str | None, top_k: int
) -> list[vector_store.ChunkHit]:
    """向量检索的发起侧：查询向量化 + 相似度检索。

    刻意不碰数据库会话：它跑在超时控制的线程池里，而 SQLAlchemy 的 Session 不是
    线程安全的。数据库的一部分（按状态过滤、取标题）留在主线程的
    `_build_vector_results` 里做。
    """
    milvus_client = vector_store.get_client(settings)
    query_vector = embed_texts([query], settings)[0]
    return vector_store.search(
        milvus_client,
        settings.milvus_collection,
        query_vector=query_vector,
        top_k=top_k,
        knowledge_type=knowledge_type,
    )


def _build_vector_results(db: Session, hits: list[vector_store.ChunkHit]) -> list[ChunkResult]:
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


def _query_terms(query: str) -> list[str]:
    """把问题切成关键词检索用的字词。

    中文没有空格分词，按相邻两字切（与画像标签的相似度计算同一套办法）；英文与数字
    按空白切。这样「管理费率是多少」能命中写着「管理费率为百分之一点二」的片段，
    而不是要求问题原文作为子串出现。
    """
    characters = [char.lower() for char in query if char.isalnum()]
    bigrams = {
        f"{characters[index]}{characters[index + 1]}" for index in range(len(characters) - 1)
    }
    # 只有真的分过词（问题里带空白）才把整段查询也算一个词；否则中文问题会被
    # `split()` 原样吐回一整个字符串，混进分母把命中率压到阈值以下。
    tokens = query.split()
    words = {token.lower() for token in tokens} if len(tokens) > 1 else set()
    terms = bigrams | words
    if not terms and query.strip():
        terms = {query.strip().lower()}
    return sorted(terms)


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _keyword_score(terms: list[str], content: str, title: str) -> float:
    if not terms:
        return 0.0
    haystack = f"{content} {title}".lower()
    matched = sum(1 for term in terms if term in haystack)
    return round(matched / len(terms), 4)


def keyword_search_chunks(
    db: Session,
    *,
    query: str,
    knowledge_type: str | None = None,
    top_k: int = 5,
) -> list[ChunkResult]:
    """面向分块镜像的关键词检索：向量检索不可用时的兜底路径。

    它只按「分块里出现了几个查询字词」打分，语义上远不如向量检索，因此只在降级时
    使用——正常路径不经过它，它也不参与正常路径的排序。
    """
    terms = _query_terms(query)
    if not terms:
        return []

    conditions = [
        KnowledgeChunk.content.like(f"%{_escape_like(term)}%", escape="\\") for term in terms
    ]
    stmt = (
        select(KnowledgeChunk, KnowledgeMeta)
        .join(KnowledgeMeta, KnowledgeMeta.id == KnowledgeChunk.knowledge_id)
        .where(KnowledgeMeta.status == STATUS_ACTIVE)
        .where(or_(*conditions))
    )
    if knowledge_type:
        stmt = stmt.where(KnowledgeChunk.knowledge_type == knowledge_type)

    scored: list[tuple[float, KnowledgeChunk, KnowledgeMeta]] = []
    for chunk, meta in db.execute(stmt.limit(KEYWORD_SCAN_LIMIT)).all():
        score = _keyword_score(terms, chunk.content, meta.title)
        if score > 0:
            scored.append((score, chunk, meta))

    scored.sort(key=lambda item: (-item[0], item[1].knowledge_id, item[1].chunk_index))
    return [
        ChunkResult(
            knowledge_id=chunk.knowledge_id,
            knowledge_type=chunk.knowledge_type,
            chunk_index=chunk.chunk_index,
            heading_path=chunk.heading_path,
            content=chunk.content,
            score=score,
            title=meta.title,
            source_file=meta.source_file,
            source="keyword",
        )
        for score, chunk, meta in scored[:top_k]
    ]


def search_chunks(
    db: Session,
    settings: Settings,
    *,
    query: str,
    knowledge_type: str | None = None,
    top_k: int = 5,
    agent_type: str | None = None,
) -> list[ChunkResult]:
    """知识检索：优先向量检索，超时或不可用时降级为关键词检索。

    向量检索是外部依赖，不是唯一路径。给它一个墙钟超时（`vector_search_timeout_seconds`），
    超时或抛错时改用分块镜像上的 MySQL LIKE 关键词检索，并写一条降级留痕。超时用
    线程池做软超时：Milvus 客户端是阻塞调用，拿不到结果就直接返回降级，不等那个线程
    收尾（与 GraphRAG 的图谱查询同一取舍）。

    回放模式（ADR-0008）不触碰 Milvus 与向量化：预置问题返回钉住的分块（内容
    与真实知识一致、分数固定，因此融合排序与引用序号确定性可复现），其余问题
    直接走 MySQL 关键词路径，连「先试一下向量库」的调用都不发起。
    """
    if settings.demo_replay:
        preset = replay_library.chat_preset(query)
        if (
            preset is not None
            and preset.chunks
            and (
                knowledge_type is None
                or all(
                    chunk.knowledge_type == knowledge_type for chunk in preset.chunks
                )
            )
        ):
            return [
                ChunkResult(
                    knowledge_id=chunk.knowledge_id,
                    knowledge_type=chunk.knowledge_type,
                    chunk_index=chunk.chunk_index,
                    heading_path=list(chunk.heading_path),
                    content=chunk.content,
                    score=chunk.score,
                    title=chunk.title,
                    source_file=chunk.source_file,
                )
                # 不按调用方的 top_k 截断：预置回答的引用序号指向这组分块的
                # 完整位置，截掉靠后的分块会让角标悬空。预置至多三条。
                for chunk in preset.chunks
            ]
        return keyword_search_chunks(
            db, query=query, knowledge_type=knowledge_type, top_k=top_k
        )

    executor = ThreadPoolExecutor(max_workers=1)
    try:
        future = executor.submit(
            _vector_search_hits,
            settings,
            query=query,
            knowledge_type=knowledge_type,
            top_k=top_k,
        )
        hits = future.result(timeout=settings.vector_search_timeout_seconds)
    except FutureTimeoutError:
        logger.warning("向量检索降级：检索超时")
        return _degraded_keyword_results(
            db,
            query=query,
            knowledge_type=knowledge_type,
            top_k=top_k,
            reason=DEGRADED_VECTOR_TIMEOUT,
            agent_type=agent_type,
        )
    except Exception as exc:  # noqa: BLE001 - 向量库边界：任何失败都退到关键词路径
        logger.warning("向量检索降级：向量库或向量化不可用", exc_info=True)
        return _degraded_keyword_results(
            db,
            query=query,
            knowledge_type=knowledge_type,
            top_k=top_k,
            reason=DEGRADED_VECTOR_UNAVAILABLE,
            agent_type=agent_type,
            detail=str(exc),
        )
    finally:
        executor.shutdown(wait=False)

    return _build_vector_results(db, hits)


def _degraded_keyword_results(
    db: Session,
    *,
    query: str,
    knowledge_type: str | None,
    top_k: int,
    reason: str,
    agent_type: str | None,
    detail: str | None = None,
) -> list[ChunkResult]:
    results = keyword_search_chunks(
        db, query=query, knowledge_type=knowledge_type, top_k=top_k
    )
    degradation.record(
        db,
        dependency=degradation.DEPENDENCY_VECTOR,
        reason=reason,
        agent_type=agent_type,
        trace_id=get_trace_id(),
        detail=detail,
    )
    return results


def _chunk_sections(sections: list[Section]) -> list[ChunkPiece]:
    pieces: list[ChunkPiece] = []
    for section in sections:
        for text in chunk_text(section.text, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
            pieces.append(ChunkPiece(heading_path=section.heading_path, text=text))
    return pieces
