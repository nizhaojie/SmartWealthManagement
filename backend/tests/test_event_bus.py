"""事件总线：信封结构、广播边界与订阅分发。

广播是增强，不是核心链路的一部分。这里的断言集中在两点上：任何发布失败都停在
`publish_safely` 里不向上冒泡——否则一次通道抖动就会让已经落库的交易回滚；订阅方
的失败彼此隔离——否则一位听众没听懂就会毁掉整次广播。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from decimal import Decimal

from app.event_bus import (
    CHANNEL_PREFIX,
    EVENT_RISK_ALERT_RAISED,
    EVENT_RISK_INTENT_DETECTED,
    SOURCE_RISK_MONITORING,
    Event,
    FanoutPublisher,
    RedisEventPublisher,
    Subscription,
    Subscriptions,
    publish_safely,
)

AT = datetime(2026, 9, 10, 11, 0, 0)


class _RecordingRedis:
    def __init__(self) -> None:
        self.published: list[tuple[str, str]] = []

    def publish(self, channel: str, message: str) -> None:
        self.published.append((channel, message))


class _BrokenPublisher:
    def publish(self, event: Event) -> None:
        raise ConnectionError("事件总线不可用")


class _OkPublisher:
    def __init__(self) -> None:
        self.events: list[Event] = []

    def publish(self, event: Event) -> None:
        self.events.append(event)


def _event() -> Event:
    return Event(
        event_type=EVENT_RISK_ALERT_RAISED,
        source=SOURCE_RISK_MONITORING,
        payload={
            "alert_id": 7,
            "customer_id": 3,
            "alert_level": "重度",
            "rule_codes": ["R001", "R019"],
            "confidence": Decimal("0.85"),
        },
        occurred_at=AT,
        trace_id="trace-1",
    )


def test_channel_is_derived_from_the_event_type():
    assert _event().channel == f"{CHANNEL_PREFIX}{EVENT_RISK_ALERT_RAISED}"


def test_message_carries_type_source_payload_timestamp_and_trace_id():
    message = json.loads(_event().as_message())

    assert message["event_type"] == EVENT_RISK_ALERT_RAISED
    assert message["source"] == SOURCE_RISK_MONITORING
    assert message["occurred_at"] == AT.isoformat()
    assert message["trace_id"] == "trace-1"
    # 中文不转义、Decimal 落成字符串：订阅方拿到的载荷要能直接读，也不该走浮点。
    assert message["payload"]["alert_level"] == "重度"
    assert message["payload"]["confidence"] == "0.85"
    assert message["payload"]["rule_codes"] == ["R001", "R019"]


def test_redis_publisher_writes_to_the_channel_of_the_event_type():
    client = _RecordingRedis()
    event = _event()

    RedisEventPublisher(client).publish(event)

    assert len(client.published) == 1
    channel, message = client.published[0]
    assert channel == event.channel
    assert json.loads(message)["payload"]["alert_id"] == 7


def test_publish_safely_returns_true_when_the_broadcast_goes_out():
    publisher = _OkPublisher()
    event = _event()

    assert publish_safely(publisher, event) is True
    assert publisher.events == [event]


def test_publish_safely_swallows_a_broken_bus_so_the_caller_keeps_going():
    """通道不可用不是调用方的错误，更不该变成一次回滚。"""
    assert publish_safely(_BrokenPublisher(), _event()) is False


# --- 订阅分发（ticket 04） ---


class _Collector:
    """一个只把事件收进列表的订阅方。"""

    def __init__(self) -> None:
        self.received: list[Event] = []

    def __call__(self, event: Event) -> None:
        self.received.append(event)


class _Exploding:
    def __call__(self, event: Event) -> None:
        raise RuntimeError("订阅方炸了")


def _subscriptions(*subscriptions: Subscription) -> Subscriptions:
    return Subscriptions(*subscriptions)


def test_a_subscriber_only_hears_the_events_it_subscribed_to():
    collector = _Collector()
    subscriptions = _subscriptions(
        Subscription(EVENT_RISK_ALERT_RAISED, "collector", collector)
    )

    subscriptions.dispatch(_event())

    assert len(collector.received) == 1
    # 换个类型就没有听众了：订阅按 event_type 过滤，不靠订阅方自己判断。
    assert subscriptions.handlers_for(EVENT_RISK_INTENT_DETECTED) == ()


def test_a_subscriber_that_explodes_does_not_stop_the_others_or_the_publisher():
    before = _Collector()
    after = _Collector()
    subscriptions = _subscriptions(
        Subscription(EVENT_RISK_ALERT_RAISED, "before", before),
        Subscription(EVENT_RISK_ALERT_RAISED, "exploding", _Exploding()),
        Subscription(EVENT_RISK_ALERT_RAISED, "after", after),
    )

    delivered = subscriptions.dispatch(_event())

    # 抛错的那个不算送达，其余两个照常，dispatch 本身不抛。
    assert delivered == 2
    assert len(before.received) == 1
    assert len(after.received) == 1


def test_a_failing_subscriber_is_named_in_the_log(caplog):
    subscriptions = _subscriptions(
        Subscription(EVENT_RISK_ALERT_RAISED, "advisory.risk_focus", _Exploding())
    )

    with caplog.at_level(logging.WARNING, logger="app.event_bus"):
        subscriptions.dispatch(_event())

    assert "advisory.risk_focus" in caplog.text


def test_adding_a_subscription_does_not_touch_the_publisher():
    """发布方拿着一份注册表，新增订阅只是往表里加一条。"""
    transport = _OkPublisher()
    subscriptions = _subscriptions(
        Subscription(EVENT_RISK_ALERT_RAISED, "first", _Collector())
    )
    publisher = FanoutPublisher(transport, subscriptions)
    publisher.publish(_event())
    assert len(transport.events) == 1

    late = _Collector()
    subscriptions.subscribe(Subscription(EVENT_RISK_ALERT_RAISED, "second", late))
    publisher.publish(_event())

    # 同一个发布方实例，订阅方多了一个，发布方一行都没改。
    assert len(late.received) == 1
    assert len(transport.events) == 2
    assert len(subscriptions.handlers_for(EVENT_RISK_ALERT_RAISED)) == 2


def test_an_unavailable_bus_still_delivers_to_in_process_subscribers(caplog):
    """通道不可用只记日志：本进程的订阅与出站镜像无关，核心链路照常。"""
    collector = _Collector()
    publisher = FanoutPublisher(
        _BrokenPublisher(),
        _subscriptions(Subscription(EVENT_RISK_ALERT_RAISED, "collector", collector)),
    )

    with caplog.at_level(logging.WARNING, logger="app.event_bus"):
        delivered = publish_safely(publisher, _event())

    # 订阅照样收到；广播则如实报成失败，由最外层的边界记日志、不让它变成回滚。
    assert len(collector.received) == 1
    assert delivered is False
    assert "事件广播失败" in caplog.text
