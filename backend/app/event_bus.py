"""事件总线：一个 Agent 广播「发生了什么」，其他 Agent 各自决定要不要听。

广播是 fire-and-forget：发布方不关心有几个订阅方，也不等它们的处理结果。核心链路
（交易落库、规则匹配、预警生成）不依赖广播通道——数据已经在库里，订阅方漏收可以
补查，但交易记录不能因为广播通道抖动而丢失。因此发布走 `publish_safely`，它吞掉
任何发布异常并记日志，调用方因此不需要为「广播失败」准备回滚分支。

信封（`Event`）固定五件事：事件类型、来源、载荷、时间戳、追踪标识。订阅方按
`event_type` 过滤，靠 `trace_id` 可以把一次请求关联到它触发的所有事件。

订阅关系收在 `Subscriptions` 注册表里：发布方按事件类型从注册表取订阅方，**新增
订阅不需要改发布方**，发布方也就无从知道有谁在听。进程内订阅与 Redis 广播是两件事：
Redis 是出站镜像（给本进程之外的消费者看），本进程的订阅方不依赖它是否可用——通道
抖动只记录日志，进程内的协作照常（见 ADR-0013）。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

import redis
from fastapi import Depends
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.redis_client import get_redis
from app.tracing import get_trace_id

logger = logging.getLogger("app.event_bus")

# 频道名沿用需求文档的口径：一个事件类型一个频道，订阅方按类型订阅。
CHANNEL_PREFIX = "event:"

EVENT_TRANSACTION_SUBMITTED = "transaction_submitted"
EVENT_RISK_ALERT_RAISED = "risk_alert"
# 客服在对话里察觉到高风险意图（例如反复打听转账限额）时广播，风控监测订阅。
EVENT_RISK_INTENT_DETECTED = "risk_intent_detected"

SOURCE_RISK_MONITORING = "risk-monitoring-agent"
SOURCE_CUSTOMER_SERVICE = "customer-service-agent"


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


@dataclass(frozen=True)
class Subscription:
    """一个订阅方。

    `name` 只用于日志：某个订阅方处理失败时，要能从日志里看出是谁没听懂。
    """

    event_type: str
    name: str
    handle: Callable[[Event], None]


class Subscriptions:
    """事件类型 → 订阅方。

    新增一条协作只是往这里加一个 `Subscription`，发布方一行都不用改。
    """

    def __init__(self, *subscriptions: Subscription) -> None:
        self._by_type: dict[str, list[Subscription]] = {}
        for subscription in subscriptions:
            self.subscribe(subscription)

    def subscribe(self, subscription: Subscription) -> None:
        self._by_type.setdefault(subscription.event_type, []).append(subscription)

    def handlers_for(self, event_type: str) -> tuple[Subscription, ...]:
        return tuple(self._by_type.get(event_type, ()))

    def dispatch(self, event: Event) -> int:
        """把事件交给它的全部订阅方，逐个隔离失败。

        一个订阅方抛错只记日志，不影响其余订阅方，也不上抛给发布方：协作是增强，
        发布方的请求此时已经成功了，没有理由因为某位听众处理不了而把它回滚。返回
        成功处理的订阅方数量——发布方不看这个值，测试与排查看。
        """
        delivered = 0
        for subscription in self.handlers_for(event.event_type):
            try:
                subscription.handle(event)
            except Exception:  # noqa: BLE001 - 订阅边界：任何订阅方失败都不许影响发布方
                logger.warning(
                    "订阅方处理失败 subscriber=%s event_type=%s trace_id=%s",
                    subscription.name,
                    event.event_type,
                    event.trace_id or get_trace_id(),
                    exc_info=True,
                )
                continue
            delivered += 1
        return delivered


class RedisEventPublisher:
    """Redis Pub/Sub 发布。

    通道不可用时 `publish` 抛 `redis.RedisError`，由 `publish_safely` 接住——
    这里不做静默吞掉，否则调用方就无从知道广播到底发出去了没有。
    """

    def __init__(self, client: redis.Redis) -> None:
        self._client = client

    def publish(self, event: Event) -> None:
        self._client.publish(event.channel, event.as_message())


class FanoutPublisher:
    """发布方：事件先出站，再交给本进程的订阅方。

    两件事互相独立，顺序是先出站后分发：镜像晚一点没有代价，本进程内的协作早一点
    更好。**分发放在 finally 里**——出站通道抖动不该让同一进程里的协作也停下来，
    这是「事件总线不可用，核心链路继续」在本层的落点。

    出站异常照常上抛，由最外层统一兜住（`publish_safely` 记日志并返回 False）：
    「广播失败不回滚」只在一处决定，这里不重复吞一次，也不谎报广播成功。
    """

    def __init__(self, transport: EventPublisher, subscriptions: Subscriptions) -> None:
        self._transport = transport
        self._subscriptions = subscriptions

    def publish(self, event: Event) -> None:
        try:
            self._transport.publish(event)
        finally:
            self._subscriptions.dispatch(event)


def _sibling_session(source: Session) -> Session:
    """订阅方自己的会话：绑定同一个引擎，但不共用请求的事务。

    共用请求会话会让「听众写失败」把发布方的事务也带进失败状态，而这正是要隔离
    的东西。另开会话后，订阅方的写入边界由它自己负责。
    """
    return Session(bind=source.get_bind())


def get_event_publisher(
    db: Session = Depends(get_session),
    client: redis.Redis = Depends(get_redis),
) -> EventPublisher:
    """请求作用域的发布方。

    订阅方要么写下自己的记录、要么什么都不做，都需要一个数据库会话，因此这里的
    发布方按请求装配。订阅清单来自 `app.event_subscribers`——延迟导入，因为订阅方
    依赖各领域模块，而事件总线本身不依赖它们。
    """
    from app.event_subscribers import build_subscriptions

    return FanoutPublisher(
        RedisEventPublisher(client),
        build_subscriptions(lambda: _sibling_session(db)),
    )


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
