from collections.abc import Iterator
from functools import lru_cache
from typing import cast

import redis

from app.replay.local_cache import InMemoryCache
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


_replay_cache: InMemoryCache | None = None


def redis_client() -> redis.Redis:
    """请求上下文之外（周期任务）用的客户端。

    回放模式（ADR-0008）不连 Redis：登录会话、短期记忆、画像缓存改用进程内
    替身，语义一致而不发起任何网络调用。替身是**进程级单例**——每个请求各发
    一个新实例的话，登录时写进的会话在下一个请求就读不到了。替身实现了各
    消费者用到的方法子集，从不抛 ``RedisError``，因此缓存降级路径不会被触发
    ——回放模式下缓存永远可用。
    """
    global _replay_cache
    settings = get_settings()
    if settings.demo_replay:
        if _replay_cache is None:
            _replay_cache = InMemoryCache()
        return cast(redis.Redis, _replay_cache)
    return _client(
        settings.redis_url,
        settings.redis_connect_timeout_seconds,
        settings.redis_socket_timeout_seconds,
    )
