from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.models import KnowledgeMeta
from app.knowledge.service import STATUS_ACTIVE, ingest_document
from app.settings import Settings, get_settings

FAQ_SOURCE_FILE = "faq_seed.md"
_FAQ_PATH = Path(__file__).resolve().parent / "fixtures" / FAQ_SOURCE_FILE


def seed_faq(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    engine = create_engine(settings.database_url)
    try:
        with Session(engine) as session:
            existing = session.scalar(
                select(KnowledgeMeta).where(
                    KnowledgeMeta.source_file == FAQ_SOURCE_FILE,
                    KnowledgeMeta.status == STATUS_ACTIVE,
                )
            )
            if existing is not None:
                return

            content = _FAQ_PATH.read_bytes()
            ingest_document(
                session,
                settings,
                filename=FAQ_SOURCE_FILE,
                content=content,
                knowledge_type="FAQ",
                title="客户常见问题",
            )
    finally:
        engine.dispose()


if __name__ == "__main__":
    seed_faq()
