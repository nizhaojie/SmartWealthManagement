from app.db.migrate import apply_schema
from app.db.seed import seed
from app.settings import get_settings


def setup(database_url: str | None = None) -> None:
    url = database_url or get_settings().database_url
    apply_schema(url)
    seed(url)


if __name__ == "__main__":
    setup()
