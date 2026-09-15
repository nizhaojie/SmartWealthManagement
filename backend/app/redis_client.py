from collections.abc import Iterator
from functools import lru_cache

import redis

from app.settings import get_settings


@lru_cache
def _client(url: str) -> redis.Redis:
    return redis.Redis.from_url(url, decode_responses=True)


def get_redis() -> Iterator[redis.Redis]:
    yield _client(get_settings().redis_url)
