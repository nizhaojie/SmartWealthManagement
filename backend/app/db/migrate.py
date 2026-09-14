from pathlib import Path

from alembic import command
from alembic.config import Config

from app.settings import get_settings

_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
_ALEMBIC_INI = _BACKEND_DIR / "alembic.ini"


def apply_schema(database_url: str | None = None) -> None:
    url = database_url or get_settings().database_url
    config = Config(str(_ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    config.attributes["configure_logging"] = False
    command.upgrade(config, "head")


if __name__ == "__main__":
    apply_schema()
