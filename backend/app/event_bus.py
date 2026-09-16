"""事件总线：交易事件落库后与预警产生后向外广播。

广播是 fire-and-forget：发布方不关心有几个订阅方，也不等它们的处理结果。核心链路
（交易落库、规则匹配、预警生成）不依赖广播通道——数据已经在库里，订阅方漏收可以
补查，但交易记录不能因为广播通道抖动而丢失。因此发布走 `publish_safely`，它吞掉
任何发布异常并记日志，调用方因此不需要为「广播失败」准备回滚分支。

信封（`Event`）固定五件事：事件类型、来源、载荷、时间戳、追踪标识。订阅方按
`event_type` 过滤，靠 `trace_id` 可以把一次请求关联到它触发的所有事件。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

import redis
from fastapi import Depends

from app.redis_client import get_redis
from app.tracing import get_trace_id

logger = logging.getLogger("app.event_bus")

# 频道名沿用需求文档的口径：一个事件类型一个频道，订阅方按类型订阅。
CHANNEL_PREFIX = "event:"

EVENT_TRANSACTION_SUBMITTED = "transaction_submitted"
EVENT_RISK_ALERT_RAISED = "risk_alert"

SOURCE_RISK_MONITORING = "risk-monitoring-agent"


@dataclass(frozen=True)
class Event:
    """事件信封：订阅方看到的第一层结构，与业务载荷分开。"""

    event_type: str
    source: str
    payload: Mapping[str, Any]
    occurred_at: datetime
    trace_id: str = ""

    @property
    def channel(self) -> str:
        return f"{CHANNEL_PREFIX}{self.event_type}"

    def as_message(self) -> str:
        """序列化成一条消息。载荷里出现 Decimal 或 datetime 时按字符串落，不炸。"""
        return json.dumps(
            {
                "event_type": self.event_type,
                "source": self.source,
                "payload": dict(self.payload),
                "occurred_at": self.occurred_at.isoformat(),
                "trace_id": self.trace_id,
            },
            ensure_ascii=False,
            default=str,
        )


class EventPublisher(Protocol):
    """发布方的唯一契约：给一个事件，让它出去。抛异常是允许的，由调用侧兜底。"""

    def publish(self, event: Event) -> None: ...


class RedisEventPublisher:
    """Redis Pub/Sub 发布。

    通道不可用时 `publish` 抛 `redis.RedisError`，由 `publish_safely` 接住——
    这里不做静默吞掉，否则调用方就无从知道广播到底发出去了没有。
    """

    def __init__(self, client: redis.Redis) -> None:
        self._client = client

    def publish(self, event: Event) -> None:
        self._client.publish(event.channel, event.as_message())


def get_event_publisher(client: redis.Redis = Depends(get_redis)) -> EventPublisher:
    return RedisEventPublisher(client)


def publish_safely(publisher: EventPublisher, event: Event) -> bool:
    """广播一个事件；失败只记日志并返回 False，绝不向上抛。

    这是「广播失败不回滚」的落点：广播是增强，核心链路的结果已经落库。任何
    发布实现（配错地址、通道掉线、订阅方报错）都不该让一笔已成交的交易消失。
    """
    try:
        publisher.publish(event)
    except Exception:  # noqa: BLE001 - 广播边界：任何发布失败都不许影响核心链路
        logger.warning(
            "事件广播失败，核心链路继续 event_type=%s trace_id=%s",
            event.event_type,
            event.trace_id or get_trace_id(),
            exc_info=True,
        )
        return False
    return True
