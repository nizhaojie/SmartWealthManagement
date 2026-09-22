"""把仓库根的 `rag_db/` 作为正式语料入库（幂等）。

`rag_db/` 是正式语料、不是演示素材，因此与 `seed_faq` 走同一条入库链路
（`ingest_document`：解析 → 分块 → 向量化 → Milvus + MySQL 镜像），并沿用同一口径的
幂等判定：同 `source_file` 且 active 的文档已存在就整份跳过。语料目录 → 知识类型按本
文件里的显式规则表落（Q12：不新增知识类型）。
"""

from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.models import KnowledgeMeta
from app.knowledge.service import STATUS_ACTIVE, ingest_document
from app.settings import Settings, get_settings

# 仓库根的 `rag_db/`：本文件在 backend/app/knowledge/ 下，往上四层。
RAG_DB_DIR = Path(__file__).resolve().parents[3] / "rag_db"

SUPPORTED_SUFFIXES = (".md", ".txt")

# 路径前缀 → 知识类型。按顺序取第一条命中的，其余落 DEFAULT_KNOWLEDGE_TYPE。
KNOWLEDGE_TYPE_RULES: tuple[tuple[str, str], ...] = (
    ("金融政策/", "政策"),
    ("公司业务/个人理财产品手册.md", "产品"),
)
DEFAULT_KNOWLEDGE_TYPE = "FAQ"


def source_files() -> list[Path]:
    return sorted(
        path
        for path in RAG_DB_DIR.rglob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
    )


def knowledge_type_for(source_file: str) -> str:
    for prefix, knowledge_type in KNOWLEDGE_TYPE_RULES:
        if source_file.startswith(prefix):
            return knowledge_type
    return DEFAULT_KNOWLEDGE_TYPE


def seed_rag_db(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    engine = create_engine(settings.database_url)
    try:
        with Session(engine) as session:
            for path in source_files():
                source_file = path.relative_to(RAG_DB_DIR).as_posix()
                if _already_ingested(session, source_file):
                    continue
                ingest_document(
                    session,
                    settings,
                    filename=source_file,
                    content=path.read_bytes(),
                    knowledge_type=knowledge_type_for(source_file),
                    title=path.stem,
                )
    finally:
        engine.dispose()


def _already_ingested(session: Session, source_file: str) -> bool:
    return (
        session.scalar(
            select(KnowledgeMeta).where(
                KnowledgeMeta.source_file == source_file,
                KnowledgeMeta.status == STATUS_ACTIVE,
            )
        )
        is not None
    )


if __name__ == "__main__":
    seed_rag_db()
