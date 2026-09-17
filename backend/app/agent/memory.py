"""短期记忆：当前会话的消息列表（三层记忆的第一层）。

分层判据是信息的生命周期与权威来源，不是存储技术（ADR-0012）。短期记忆的特点是
「随会话结束失去意义」：它是一次登录期间对话本身产生的上下文，所以

- 按会话标识隔离，会话不跨登录延续（每次登录签发新的 ``sid``，下一层由鉴权保证）；
- 滑动过期，每次追加都重置 TTL（`chat_memory_ttl_minutes`），不再说话就自然消失；
- 总量受 token 预算约束，超预算时从最旧的消息开始截断，最新的消息一定保留。

这里的消息列表只用于组装上下文，不是留痕：会话归档（`app.agent.archive`）是另一回事，
它永久保存、脱敏后只读，不参与上下文组装。
"""

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
