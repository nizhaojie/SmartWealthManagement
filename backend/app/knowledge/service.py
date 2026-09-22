import logging
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal, TypeVar

from rank_bm25 import BM25Okapi
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app import degradation
from app.db.models import KnowledgeChunk, KnowledgeMeta
from app.exceptions import AppError
from app.knowledge import object_store, vector_store
from app.knowledge.embeddings import embed_texts
from app.knowledge.hybrid import rrf_fuse, tokenize
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
    # `score` 是**最终排序分**（由融合/重排写出，0~1），`evidence_score` 是该块在
    # **其来源臂上的原始分**（余弦 / BM25 / 图谱 1.0）。两者混用是这套设计最容易
    # 失控的地方：兜底判定只读 `evidence_score` 各自的量纲，排序只读 `score`。
    score: float
    title: str
    source_file: str
    evidence_score: float = 0.0
    # 结果来源：向量臂 "vector"、关键词臂 "keyword"、两路都命中 "hybrid"；
    # 图谱查询产出的段落用 "graph" 构造同类型对象，以便和相似度结果一起排序。
    # 注意它不再表示健康度——「出现过关键词路径」不再等于「向量库坏了」，
    # 判断降级要看 `biz_degradation_trace`（ADR-0022）。
    source: Literal["vector", "graph", "keyword", "hybrid"] = "vector"


class RetrievedChunks(list[ChunkResult]):
    """检索候选 + 各召回臂的原始最高分（分臂判定的输入）。

    `ChunkResult.evidence_score` 是**单块**在其来源臂上的分；但 hybrid 块两路取大
    之后，「向量臂最高多少、关键词臂最高多少」已经无法从候选里还原了——拿 BM25 的
    量纲去冒充余弦，会让向量臂凭空达标。所以臂内最高分在两路还分着的时候
    （`search_chunks` 内）就算好带出来，而不是事后从融合结果反推。
    """

    def __init__(
        self, chunks: Iterable[ChunkResult], evidence: dict[str, float]
    ) -> None:
        super().__init__(chunks)
        self.evidence = evidence


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
                # 向量臂的原始分就是余弦相似度，先落进 evidence_score；
                # 最终排序分由 RRF 融合（或重排）写回 `score`。
                evidence_score=hit["score"],
            )
        )
    return results


def keyword_search_chunks(
    db: Session,
    *,
    query: str,
    knowledge_type: str | None = None,
    top_k: int = 5,
    user_dict_path: str = "",
) -> list[ChunkResult]:
    """面向分块镜像（`fin_knowledge_chunk`）的 BM25 召回臂。

    它是一等召回臂：正常路径与向量臂并行发起，两路的位次再交给 RRF 融合；向量臂
    超时或不可用时，它也是那条唯一路径——降级路径与正常路径共用这一份实现、
    一套口径（ADR-0022）。

    BM25 的 df / avgdl 在**全语料**（所有 active 分块）上统计，`knowledge_type`
    只过滤**结果**、不过滤语料：按类型把语料切小会让词频统计在子集上失真。索引
    每次查询现建——当前语料是百级分块、单次几十毫秒，进程内缓存与失效（多 worker
    下会漂移）留到真有瓶颈时再说。
    """
    query_tokens = tokenize(query, user_dict_path=user_dict_path)
    if not query_tokens:
        return []

    corpus = db.execute(
        select(KnowledgeChunk, KnowledgeMeta)
        .join(KnowledgeMeta, KnowledgeMeta.id == KnowledgeChunk.knowledge_id)
        .where(KnowledgeMeta.status == STATUS_ACTIVE)
    ).all()
    if not corpus:
        return []

    tokenized_corpus = [
        tokenize(chunk.content, user_dict_path=user_dict_path) for chunk, _ in corpus
    ]
    if not any(tokenized_corpus):
        # BM25 的 avgdl 会变成 0（除零）——语料全是标点这种退化情形直接返回空。
        return []

    scores = BM25Okapi(tokenized_corpus).get_scores(query_tokens)

    scored: list[tuple[float, KnowledgeChunk, KnowledgeMeta]] = []
    for (chunk, meta), raw_score in zip(corpus, scores):
        if knowledge_type and chunk.knowledge_type != knowledge_type:
            continue
        # 与查询没有任何词重叠的块不是命中，不进候选：BM25 对无重叠词给 0 分。
        if raw_score <= 0:
            continue
        scored.append((float(raw_score), chunk, meta))

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
            evidence_score=score,
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
) -> RetrievedChunks:
    """知识检索：向量臂与关键词臂并行召回，RRF 融合成候选。

    两臂各出 `hybrid_recall_top_k` 条，融合后的候选按 RRF 位次排序、整体重排由
    调用方接上（见 `app.agent.graph` 与 `app.knowledge.rerank`）。

    向量臂是外部依赖（Milvus），给它一个墙钟超时（`vector_search_timeout_seconds`）：
    超时或抛错时**只是少了一路召回**，结果退回「只用关键词臂的排序」，并写一条降级
    留痕。超时用线程池做软超时：Milvus 客户端是阻塞调用，拿不到结果就直接返回，
    不等那个线程收尾（与 GraphRAG 的图谱查询同一取舍）。

    关键词臂在主线程跑——SQLAlchemy 的 `Session` 不是线程安全的；它提交给向量臂
    的线程之后立刻开始，因此两臂是并行而不是「先向量后关键词」。

    回放模式（ADR-0008）不触碰 Milvus 与向量化：预置问题返回钉住的分块（内容
    与真实知识一致、分数固定，因此融合排序与引用序号确定性可复现），其余问题
    直接走本地 BM25 路径，连「先试一下向量库」的调用都不发起。
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
            preset_chunks = [
                ChunkResult(
                    knowledge_id=chunk.knowledge_id,
                    knowledge_type=chunk.knowledge_type,
                    chunk_index=chunk.chunk_index,
                    heading_path=list(chunk.heading_path),
                    content=chunk.content,
                    score=chunk.score,
                    title=chunk.title,
                    source_file=chunk.source_file,
                    # 预置分同时充当证据分：回放里没有臂内原始分可言，
                    # 既有回放断言（按 score 比阈值）因此仍然成立。
                    evidence_score=chunk.score,
                )
                # 不按调用方的 top_k 截断：预置回答的引用序号指向这组分块的
                # 完整位置，截掉靠后的分块会让角标悬空。预置至多三条。
                for chunk in preset.chunks
            ]
            return RetrievedChunks(preset_chunks, _arm_evidence(preset_chunks, []))
        keyword_results = keyword_search_chunks(
            db,
            query=query,
            knowledge_type=knowledge_type,
            top_k=top_k,
            user_dict_path=settings.jieba_user_dict_path,
        )
        return RetrievedChunks(keyword_results, _arm_evidence([], keyword_results))

    executor = ThreadPoolExecutor(max_workers=1)
    try:
        vector_future = executor.submit(
            _vector_search_hits,
            settings,
            query=query,
            knowledge_type=knowledge_type,
            top_k=settings.hybrid_recall_top_k,
        )
        keyword_results = keyword_search_chunks(
            db,
            query=query,
            knowledge_type=knowledge_type,
            top_k=settings.hybrid_recall_top_k,
            user_dict_path=settings.jieba_user_dict_path,
        )
        try:
            hits = vector_future.result(timeout=settings.vector_search_timeout_seconds)
        except FutureTimeoutError:
            logger.warning("向量臂降级：检索超时，只用关键词臂")
            return _keyword_only_results(
                db,
                keyword_results,
                settings,
                top_k=top_k,
                reason=DEGRADED_VECTOR_TIMEOUT,
                agent_type=agent_type,
            )
        except Exception as exc:  # noqa: BLE001 - 向量库边界：任何失败都退到单臂
            logger.warning("向量臂降级：向量库或向量化不可用，只用关键词臂", exc_info=True)
            return _keyword_only_results(
                db,
                keyword_results,
                settings,
                top_k=top_k,
                reason=DEGRADED_VECTOR_UNAVAILABLE,
                agent_type=agent_type,
                detail=str(exc),
            )
        vector_results = _build_vector_results(db, hits)
    finally:
        executor.shutdown(wait=False)

    fused = rrf_fuse([vector_results, keyword_results], rrf_k=settings.rrf_k, top_k=top_k)
    return RetrievedChunks(fused, _arm_evidence(vector_results, keyword_results))


def _keyword_only_results(
    db: Session,
    keyword_results: list[ChunkResult],
    settings: Settings,
    *,
    top_k: int,
    reason: str,
    agent_type: str | None,
    detail: str | None = None,
) -> RetrievedChunks:
    """向量臂不可用时的返回：只用已经拿到的关键词臂排一遍，并留一条降级痕迹。

    不另起一次关键词检索——关键词臂本来就在正常路径上跑，向量臂的缺席只是少了
    一路召回。留痕的写入点与原因码都不变，降级统计口径因此不受影响。
    """
    degradation.record(
        db,
        dependency=degradation.DEPENDENCY_VECTOR,
        reason=reason,
        agent_type=agent_type,
        trace_id=get_trace_id(),
        detail=detail,
    )
    fused = rrf_fuse([keyword_results], rrf_k=settings.rrf_k, top_k=top_k)
    return RetrievedChunks(fused, _arm_evidence([], keyword_results))


def _arm_evidence(
    vector_results: list[ChunkResult], keyword_results: list[ChunkResult]
) -> dict[str, float]:
    """在两路还分着的时候取各臂的最高原始分（分臂判定的输入）。

    这就是 `RetrievedChunks` 存在的理由：一旦 RRF 把 hybrid 块合成一条，臂与臂的
    分就再也分不开了，而 BM25 的量纲冒充余弦会让向量臂凭空达标。
    """
    return {
        "vector": max((chunk.evidence_score for chunk in vector_results), default=0.0),
        "keyword": max((chunk.evidence_score for chunk in keyword_results), default=0.0),
        "graph": 0.0,
    }


def _chunk_sections(sections: list[Section]) -> list[ChunkPiece]:
    pieces: list[ChunkPiece] = []
    for section in sections:
        for text in chunk_text(section.text, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
            pieces.append(ChunkPiece(heading_path=section.heading_path, text=text))
    return pieces
