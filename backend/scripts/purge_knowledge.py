"""清理知识库：只留正式语料那 10 篇，其余一律清掉。

用法::

    cd backend
    python -m scripts.purge_knowledge --dry-run   # 只报要删什么，不动手
    python -m scripts.purge_knowledge             # 真清

**什么叫「正式语料」。** 只有 `seed_rag_db.source_files()` 读的 `rag_db/` 下那 9 篇，
加上 `seed_faq` 灌的 `faq_seed.md`——正好 10 篇 / 348 分块，与 `app/settings.py` 里
检索阈值校准注释记的语料规模一致。判定按 `source_file` 且 `status='active'`，与两条
播种链路的幂等键同一口径：清完之后再跑 `python -m app.db.setup` 不会重新灌进来。

**清掉的四类残留**（都是历次测试、演示与手工上传留下的）：

| 残留 | 量 | 来处 |
|---|---|---|
| MinIO 对象 | 5900+ 个 | 测试与手工上传的文件。测试与开发**共用一个桶**（settings 里没有 test 版桶），每跑一次测试就多几件 |
| `expired` 旧版本 | 19 篇 | 同一批正式语料被重复上传产生的历史副本（分块镜像还在） |
| 手工上传的文档 | 3 篇 | 《三国演义》.txt（1336 分块，active 那份**真的在参与检索**）、MOCKRAG240924.md |
| 分页演示文档 | 40 篇 | `app.db.pagination_demo_seed` 直接写元数据造的，从未 ingest，没有向量与对象 |

**为什么必须三处一起清。** 知识库的权威副本在 Milvus、原文在 MinIO、元数据与分块
镜像在 MySQL，靠 `fin_knowledge_meta.id` 串联：

- 只删元数据 → Milvus 里留下**孤儿向量**。产品接口删不掉它们（`delete_document` 对已
  下架文档直接 404），而向量臂的消费端**只按 `status='active'` 过滤**，所以一份被重新
  上传过的文档会让孤儿重新变得可见；
- 只删 Milvus → 关键词臂读的是 `fin_knowledge_chunk` 镜像，过期文档的分块不随下架消失
  （`test_degradation_paths.py` 明确钉住这条口径），BM25 语料里仍然留着它们；
- MinIO 里的对象不物理删（下架只打 `archived=true` 标签），但这里是清理残留，
  因此物理删除。

删的顺序与 `delete_document` 一致：**先外部存储，后数据库**——中途出错时库里的行还
在，不会留下「文档在、向量没了」这种更难发现的状态。
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass

from minio.deleteobjects import DeleteObject
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import Session

from app.db.models import KnowledgeChunk, KnowledgeMeta
from app.knowledge import object_store, vector_store
from app.knowledge.seed_faq import FAQ_SOURCE_FILE
from app.knowledge.seed_rag_db import RAG_DB_DIR, source_files
from app.knowledge.service import STATUS_ACTIVE
from app.settings import get_settings

# MinIO 一次删除的对象数：几千个小对象逐个删要几千次往返，批量走一把。
_MINIO_BATCH = 500


@dataclass(frozen=True)
class Document:
    """一篇文档在账里只需要这几个字段——**不持有 ORM 对象**。

    提交之后会话关闭，ORM 实例的属性会过期，再读一个就抛
    `DetachedInstanceError`；报表在提交之后才打印，所以账目必须是值而不是引用。
    """

    id: int
    status: str
    source_file: str
    # 保留文档在 MinIO 里的原始对象：它按 `knowledge/{id}/{source_file}` 落，
    # 清对象时留的就是这几件。
    minio_path: str | None


@dataclass(frozen=True)
class Plan:
    """一次清理的账：留下谁、清掉谁。`--dry-run` 打印的就是它。"""

    keep_documents: tuple[Document, ...]
    doomed_documents: tuple[Document, ...]
    doomed_chunk_rows: int
    doomed_vectors: tuple[int, ...]
    doomed_objects: tuple[str, ...]
    total_objects: int


def canonical_source_files() -> set[str]:
    """正式语料的 `source_file` 集合：`rag_db/` 那 9 篇 + `faq_seed.md`。"""
    return {path.relative_to(RAG_DB_DIR).as_posix() for path in source_files()} | {
        FAQ_SOURCE_FILE
    }


def canonical_documents(session: Session) -> tuple[Document, ...]:
    """当前库里对得上正式语料、且 active 的那几篇。

    同一 `source_file` 出现两篇 active 属于异常（播种链路的幂等键会失效），
    因此报错让人工确认，而不是随手留一篇。
    """
    expected = canonical_source_files()
    rows = tuple(
        _as_document(row)
        for row in session.scalars(
            select(KnowledgeMeta)
            .where(KnowledgeMeta.source_file.in_(expected), KnowledgeMeta.status == STATUS_ACTIVE)
            .order_by(KnowledgeMeta.source_file)
        ).all()
    )
    found = [row.source_file for row in rows]
    duplicated = {name for name in found if found.count(name) > 1}
    if duplicated:
        raise RuntimeError(f"同一 source_file 有多篇 active 文档，请先人工确认：{sorted(duplicated)}")
    missing = expected - set(found)
    if missing:
        raise RuntimeError(
            "正式语料缺篇："
            + "、".join(sorted(missing))
            + "。先执行 `python -m app.db.setup` 把它灌进来（或确认 rag_db/ 里文件还在）。"
        )
    return rows


def _as_document(row: KnowledgeMeta) -> Document:
    return Document(
        id=row.id, status=row.status, source_file=row.source_file, minio_path=row.minio_path
    )


def build_plan(session: Session, settings) -> Plan:
    keep = canonical_documents(session)
    keep_ids = [row.id for row in keep]

    doomed_documents = tuple(
        _as_document(row)
        for row in session.scalars(
            select(KnowledgeMeta)
            .where(KnowledgeMeta.id.not_in(keep_ids))
            .order_by(KnowledgeMeta.id)
        ).all()
    )
    doomed_chunk_rows = session.scalar(
        select(func.count()).select_from(KnowledgeChunk).where(KnowledgeChunk.knowledge_id.not_in(keep_ids))
    )
    # 向量与对象按**实际存在的**算，不按「哪些文档要删」算：孤儿（文档已删、向量还在）
    # 正是要清掉的那一类，它不会出现在 doomed_documents 里。
    doomed_vectors = tuple(
        sorted(_milvus_knowledge_ids(settings) - set(keep_ids))
    )
    keep_object_paths = {row.minio_path for row in keep if row.minio_path}
    all_objects = [item.object_name for item in _minio_objects(settings)]
    doomed_objects = tuple(name for name in all_objects if name not in keep_object_paths)

    return Plan(
        keep_documents=keep,
        doomed_documents=doomed_documents,
        doomed_chunk_rows=doomed_chunk_rows,
        doomed_vectors=doomed_vectors,
        doomed_objects=doomed_objects,
        total_objects=len(all_objects),
    )


def purge(database_url: str | None = None, *, dry_run: bool = False) -> Plan:
    settings = get_settings()
    url = database_url or settings.database_url
    engine = create_engine(url)
    try:
        with Session(engine) as session:
            plan = build_plan(session, settings)
            if dry_run:
                return plan

            _purge_milvus(settings, plan.doomed_vectors)
            _purge_minio(settings, plan.doomed_objects)

            keep_ids = [row.id for row in plan.keep_documents]
            session.execute(
                delete(KnowledgeChunk).where(KnowledgeChunk.knowledge_id.not_in(keep_ids))
            )
            session.execute(delete(KnowledgeMeta).where(KnowledgeMeta.id.not_in(keep_ids)))
            session.commit()
            return plan
    finally:
        engine.dispose()


def _milvus_knowledge_ids(settings) -> set[int]:
    """集合里现存向量涉及哪些 `knowledge_id`（分块数按 id 去重）。"""
    client = vector_store.get_client(settings)
    collection = settings.milvus_collection
    if not client.has_collection(collection):
        return set()
    rows = client.query(
        collection,
        filter="knowledge_id >= 0",
        output_fields=["knowledge_id"],
        limit=16384,
    )
    return {row["knowledge_id"] for row in rows}


def _purge_milvus(settings, knowledge_ids: tuple[int, ...]) -> None:
    client = vector_store.get_client(settings)
    for knowledge_id in knowledge_ids:
        vector_store.delete_by_knowledge_id(client, settings.milvus_collection, knowledge_id)


def _minio_objects(settings) -> list:
    client = object_store.get_client(settings)
    if not client.bucket_exists(settings.minio_bucket):
        return []
    return list(client.list_objects(settings.minio_bucket, recursive=True))


def _purge_minio(settings, object_names: tuple[str, ...]) -> None:
    if not object_names:
        return
    client = object_store.get_client(settings)
    bucket = settings.minio_bucket
    for start in range(0, len(object_names), _MINIO_BATCH):
        batch = object_names[start : start + _MINIO_BATCH]
        errors = list(
            client.remove_objects(bucket, [DeleteObject(name) for name in batch])
        )
        if errors:
            raise RuntimeError(f"MinIO 删除失败 {len(errors)} 个对象，首个：{errors[0]}")


def _report(plan: Plan, *, dry_run: bool) -> None:
    head = "将要清理" if dry_run else "已清理"
    print(f"[purge_knowledge] {head}：")
    print(f"  保留文档 {len(plan.keep_documents)} 篇（正式语料）")
    for row in plan.keep_documents:
        print(f"    id={row.id:<5} {row.source_file}")
    print(f"  删除文档 {len(plan.doomed_documents)} 篇、分块镜像 {plan.doomed_chunk_rows} 行")
    if plan.doomed_documents:
        for row in plan.doomed_documents[:12]:
            print(f"    id={row.id:<5} status={row.status:<8} {row.source_file}")
        if len(plan.doomed_documents) > 12:
            print(f"    ...（其余 {len(plan.doomed_documents) - 12} 篇）")
    print(f"  删除 Milvus 向量：knowledge_id {list(plan.doomed_vectors)}")
    print(f"  删除 MinIO 对象 {len(plan.doomed_objects)} 个（桶内共 {plan.total_objects} 个）")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="清理知识库残留，只留正式语料那 10 篇")
    parser.add_argument("--database-url", default=None, help="默认取 settings.database_url（wealth 库）")
    parser.add_argument("--dry-run", action="store_true", help="只报表，不删任何东西")
    args = parser.parse_args(argv)

    plan = purge(args.database_url, dry_run=args.dry_run)
    _report(plan, dry_run=args.dry_run)

    if args.dry_run:
        print("[purge_knowledge] --dry-run：没有删除任何东西。去掉该参数即执行。")
        return 0

    print("[purge_knowledge] 清理后核对：")
    settings = get_settings()
    engine = create_engine(args.database_url or settings.database_url)
    try:
        with Session(engine) as session:
            docs = session.scalar(select(func.count()).select_from(KnowledgeMeta))
            active = session.scalar(
                select(func.count()).select_from(KnowledgeMeta).where(
                    KnowledgeMeta.status == STATUS_ACTIVE
                )
            )
            chunks = session.scalar(select(func.count()).select_from(KnowledgeChunk))
    finally:
        engine.dispose()
    remaining_vectors = _milvus_knowledge_ids(settings)
    print(f"  文档 {docs} 篇（active {active}）、分块镜像 {chunks} 行")
    print(f"  Milvus 剩余 knowledge_id：{sorted(remaining_vectors)}")
    print(f"  MinIO 剩余对象 {len(_minio_objects(settings))} 个")
    return 0


if __name__ == "__main__":
    sys.exit(main())
