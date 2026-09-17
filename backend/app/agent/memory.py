"""短期记忆：当前会话的消息列表（三层记忆的第一层）。

分层判据是信息的生命周期与权威来源，不是存储技术（ADR-0012）。短期记忆的特点是
「随会话结束失去意义」：它是一次登录期间对话本身产生的上下文，所以：

- 按会话标识隔离，会话不跨登录延续（每次登录签发新的 ``sid``，下一层由鉴权保证）；
- 滑动过期，每次追加都重置 TTL（`chat_memory_ttl_minutes`），不再说话就自然消失；
- 总量受 token 预算约束，超预算时从最旧的消息开始截断，最新的消息一定保留。

缓存是优化不是依赖：Redis 不可用时**不抛异常**——读历史返回空列表，追加静默跳过。
这一轮对话因此退化成「没有上下文的一轮」，但仍然能正常作答，并由调用方写一条降级
留痕。会话归档（`app.agent.archive`）是另一回事，它永久保存、脱敏后只读，不参与
上下文组装；本轮对话不会因为缓存抖动而丢掉审计级留痕。

这里的消息列表只用于组装上下文，不是留痕。
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import timedelta

import redis

from app.knowledge.tokenizer import count_tokens
from app.settings import Settings

logger = logging.getLogger("app.memory")

_KEY_PREFIX = "agent:memory:"


def _key(session_id: str) -> str:
    return f"{_KEY_PREFIX}{session_id}"


@dataclass(frozen=True)
class HistoryRead:
    """一次读取的结果：消息列表，以及这次读取是否走了降级（缓存不可用）。"""

    history: list[dict] = field(default_factory=list)
    degraded: bool = False


def read_history(cache: redis.Redis, session_id: str) -> HistoryRead:
    try:
        raw_messages = cache.lrange(_key(session_id), 0, -1)
    except redis.RedisError:
        logger.warning("短期记忆降级：缓存不可用，本轮不带上下文", exc_info=True)
        return HistoryRead(history=[], degraded=True)
    return HistoryRead(history=[json.loads(raw) for raw in raw_messages])


def get_history(cache: redis.Redis, session_id: str) -> list[dict]:
    """只取消息列表的便捷读法；需要知道是否降级时用 ``read_history``。"""
    return read_history(cache, session_id).history


def append_turn(
    cache: redis.Redis,
    session_id: str,
    *,
    role: str,
    content: str,
    settings: Settings,
) -> bool:
    """追加一轮消息，返回是否写成功。缓存不可用时返回 False 而不是抛错。"""
    key = _key(session_id)
    try:
        cache.rpush(key, json.dumps({"role": role, "content": content}))
        cache.expire(key, timedelta(minutes=settings.chat_memory_ttl_minutes))
    except redis.RedisError:
        logger.warning("短期记忆降级：缓存不可用，本轮不进上下文", exc_info=True)
        return False
    return _truncate_to_budget(cache, key, settings.chat_memory_token_budget)


def _truncate_to_budget(cache: redis.Redis, key: str, token_budget: int) -> bool:
    try:
        raw_messages = cache.lrange(key, 0, -1)
        messages = [json.loads(raw) for raw in raw_messages]
        total = sum(count_tokens(message["content"]) for message in messages)

        dropped = 0
        while total > token_budget and len(messages) - dropped > 1:
            total -= count_tokens(messages[dropped]["content"])
            dropped += 1

        if dropped:
            cache.ltrim(key, dropped, -1)
    except redis.RedisError:
        # 截断失败不影响本轮：消息已经写进去，超预算的上下文下一轮读出来时
        # 仍会被调用方按同样的预算处理。
        logger.warning("短期记忆降级：截断失败", exc_info=True)
        return False
    return True
