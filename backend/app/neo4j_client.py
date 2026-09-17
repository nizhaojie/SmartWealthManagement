from collections.abc import Iterator
from functools import lru_cache

from neo4j import Driver, GraphDatabase

from app.settings import get_settings


@lru_cache
def _driver(uri: str, user: str, password: str, connection_timeout: float) -> Driver:
    # 建连超时必须设：不设时网络抖动会让 driver 在建立连接上无限等待，
    # 「图谱超时跳过增强」就永远等不到那个超时。
    return GraphDatabase.driver(
        uri,
        auth=(user, password),
        connection_timeout=connection_timeout,
    )


def get_neo4j() -> Iterator[Driver]:
    settings = get_settings()
    yield _driver(
        settings.neo4j_uri,
        settings.neo4j_user,
        settings.neo4j_password,
        settings.neo4j_connection_timeout_seconds,
    )
