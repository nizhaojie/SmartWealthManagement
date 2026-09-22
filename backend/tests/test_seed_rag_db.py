"""`rag_db/` 正式语料的幂等 seed（`rag-retrieval-upgrade` 01）。

Seam：seed 脚本本身 + 测试库里的文档元数据。断言两件事：目录 → 知识类型按脚本里那张
显式映射表落库，以及跑两次只落一份（与 `seed_faq` 同一口径：同 `source_file` 且 active 即跳过）。
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session as OrmSession

from app.db.models import KnowledgeMeta
from app.knowledge.seed_rag_db import seed_rag_db
from app.knowledge.service import STATUS_ACTIVE, delete_document
from app.settings import Settings, get_settings

# rag_db/ 的目录 → 知识类型（Q12：不新增知识类型，「公司信息」归 FAQ）。
EXPECTED_TYPES = {
    "金融政策/个人投资者适当性管理指南.md": "政策",
    "金融政策/反洗钱合规操作手册.md": "政策",
    "金融政策/理财产品销售管理办法.md": "政策",
    "公司业务/个人理财产品手册.md": "产品",
    "公司业务/企业金融服务方案.md": "FAQ",
    "公司业务/高净值客户服务规范.md": "FAQ",
    "公司信息/企业信息.md": "FAQ",
    "公司信息/公司新人指南.md": "FAQ",
    "公司信息/高频问答对.txt": "FAQ",
}


@pytest.fixture
def seed_settings() -> Settings:
    base = get_settings()
    return base.model_copy(
        update={
            "database_url": base.test_database_url,
            "milvus_collection": base.test_milvus_collection,
            "embedding_api_key": "",
        }
    )


@pytest.fixture
def seeded_corpus(seed_settings: Settings) -> Iterator[Settings]:
    """seed 一遍 `rag_db/`，用完把这一批文档下架。

    这九份是真实语料，但测试库是所有用例共用的：把它们留在库里会改变其他用例的检索
    排序（关键词兜底路径按命中字面量打分，语料一多就出现并列，排在前面的就不再是那个
    用例自己上传的文档）。本文件要验证的是 seed 的行为，验完还原。
    """
    seed_rag_db(seed_settings)
    try:
        yield seed_settings
    finally:
        _drop_corpus(seed_settings)


def _active_corpus(session: OrmSession) -> list[KnowledgeMeta]:
    return list(
        session.scalars(
            select(KnowledgeMeta)
            .where(KnowledgeMeta.source_file.in_(EXPECTED_TYPES))
            .where(KnowledgeMeta.status == STATUS_ACTIVE)
            .order_by(KnowledgeMeta.source_file)
        )
    )


def _corpus_rows(settings: Settings) -> list[KnowledgeMeta]:
    engine = create_engine(settings.database_url)
    try:
        with OrmSession(engine) as session:
            return _active_corpus(session)
    finally:
        engine.dispose()


def _drop_corpus(settings: Settings) -> None:
    engine = create_engine(settings.database_url)
    try:
        with OrmSession(engine) as session:
            for meta in _active_corpus(session):
                delete_document(session, settings, meta.id)
    finally:
        engine.dispose()


def test_seed_rag_db_imports_the_corpus_with_the_directory_type_mapping(seeded_corpus):
    metas = {meta.source_file: meta for meta in _corpus_rows(seeded_corpus)}

    assert set(metas) == set(EXPECTED_TYPES)
    for source_file, knowledge_type in EXPECTED_TYPES.items():
        meta = metas[source_file]
        assert meta.knowledge_type == knowledge_type
        # source_file 是相对 rag_db/ 的 POSIX 路径，title 是文件名去扩展名。
        assert meta.title == Path(source_file).stem
        assert meta.chunk_count > 0


def test_seed_rag_db_is_idempotent(seeded_corpus):
    first = _corpus_rows(seeded_corpus)

    seed_rag_db(seeded_corpus)
    second = _corpus_rows(seeded_corpus)

    # 第一遍真的落了库；第二遍同 source_file 且 active 的文档整份跳过（不重切块、不新建文档）。
    assert len(first) == len(EXPECTED_TYPES)
    assert [(meta.id, meta.chunk_count) for meta in second] == [
        (meta.id, meta.chunk_count) for meta in first
    ]
