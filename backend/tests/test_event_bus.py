"""事件总线：信封结构与广播边界。

广播是增强，不是核心链路的一部分。这里的断言集中在一点上：任何发布失败都停在
`publish_safely` 里，不向上冒泡——否则一次通道抖动就会让已经落库的交易回滚。
"""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal

from app.event_bus import (
    CHANNEL_PREFIX,
    EVENT_RISK_ALERT_RAISED,
    SOURCE_RISK_MONITORING,
    Event,
    RedisEventPublisher,
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
