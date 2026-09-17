from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.settings import get_settings


@lru_cache
def _engine(url: str) -> Engine:
    return create_engine(url, pool_pre_ping=True)


def get_session() -> Iterator[Session]:
    engine = _engine(get_settings().database_url)
    with Session(engine) as session:
        yield session


def open_session() -> Session:
    """请求上下文之外（周期任务）用的会话工厂，调用方负责关闭。"""
    return Session(_engine(get_settings().database_url))
