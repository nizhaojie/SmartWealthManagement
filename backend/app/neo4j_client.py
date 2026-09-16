from collections.abc import Iterator
from functools import lru_cache

from neo4j import Driver, GraphDatabase

from app.settings import get_settings


@lru_cache
def _driver(uri: str, user: str, password: str) -> Driver:
    return GraphDatabase.driver(uri, auth=(user, password))


def get_neo4j() -> Iterator[Driver]:
    settings = get_settings()
    yield _driver(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password)
