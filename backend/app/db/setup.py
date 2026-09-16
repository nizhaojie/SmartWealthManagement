from app.db.analytics_account import setup_analytics_account
from app.db.migrate import apply_schema
from app.db.seed import seed
from app.knowledge.seed_faq import seed_faq
from app.settings import get_settings


def setup(database_url: str | None = None) -> None:
    settings = get_settings()
    url = database_url or settings.database_url
    apply_schema(url)
    seed(url)
    seed_faq(settings.model_copy(update={"database_url": url}))
    # 受限执行账号的授权要求视图已存在，因此放在迁移之后。
    setup_analytics_account(url)


if __name__ == "__main__":
    setup()
