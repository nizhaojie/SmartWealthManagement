from collections.abc import Iterator
from functools import lru_cache

import redis

from app.settings import get_settings


@lru_cache
def _client(
    url: str, connect_timeout: float, socket_timeout: float
) -> redis.Redis:
    """连接与读写都设超时。

    不设时一次「连得上但不应答」的抖动会把请求线程一直吊着——「缓存不可用就直连
    数据库」也就永远触发不了，因为永远等不到那个异常。
    """
    return redis.Redis.from_url(
        url,
        decode_responses=True,
        socket_connect_timeout=connect_timeout,
        socket_timeout=socket_timeout,
    )


def get_redis() -> Iterator[redis.Redis]:
    yield redis_client()


def redis_client() -> redis.Redis:
    """请求上下文之外（周期任务）用的客户端。"""
    settings = get_settings()
    return _client(
        settings.redis_url,
        settings.redis_connect_timeout_seconds,
        settings.redis_socket_timeout_seconds,
    )
