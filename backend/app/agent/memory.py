import json
from datetime import timedelta

import redis

from app.knowledge.tokenizer import count_tokens
from app.settings import Settings

_KEY_PREFIX = "agent:memory:"


def _key(session_id: str) -> str:
    return f"{_KEY_PREFIX}{session_id}"


def get_history(cache: redis.Redis, session_id: str) -> list[dict]:
    raw_messages = cache.lrange(_key(session_id), 0, -1)
    return [json.loads(raw) for raw in raw_messages]


def append_turn(
    cache: redis.Redis,
    session_id: str,
    *,
    role: str,
    content: str,
    settings: Settings,
) -> None:
    key = _key(session_id)
    cache.rpush(key, json.dumps({"role": role, "content": content}))
    cache.expire(key, timedelta(minutes=settings.chat_memory_ttl_minutes))
    _truncate_to_budget(cache, key, settings.chat_memory_token_budget)


def _truncate_to_budget(cache: redis.Redis, key: str, token_budget: int) -> None:
    raw_messages = cache.lrange(key, 0, -1)
    messages = [json.loads(raw) for raw in raw_messages]
    total = sum(count_tokens(message["content"]) for message in messages)

    dropped = 0
    while total > token_budget and len(messages) - dropped > 1:
        total -= count_tokens(messages[dropped]["content"])
        dropped += 1

    if dropped:
        cache.ltrim(key, dropped, -1)
