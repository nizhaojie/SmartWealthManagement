"""把各 Agent 的订阅接到事件总线上。

新增一条协作只是在这里加一个 `Subscription`：发布方（风控监测、智能客服）不 import
本模块，因此不知道有谁在听、有几个在听。本 slice 落地两条：

- 风控预警 → 投顾助手为这位客户记下风险关注，生成方案时带上风险标记；
- 客服察觉到高风险意图 → 风控监测为这位客户记下一条风险关注。

两个方向只有「记下来的那条长什么样」不同，怎么落库、失败怎么隔离是同一件事，因此
handler 只有一个，差别收在 `_FocusSpec` 里。

订阅方**只写自己那一条记录**，不修改发布方的数据、也不回头通知发布方。它们的失败
由 `Subscriptions.dispatch` 逐个隔离：一位听众没听懂，不影响发布方已经完成的请求，
也不影响其他听众。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app import risk_focus
from app.event_bus import (
    EVENT_RISK_ALERT_RAISED,
    EVENT_RISK_INTENT_DETECTED,
    Event,
    Subscription,
    Subscriptions,
)

SessionFactory = Callable[[], Session]
# 订阅方在处理时另开自己的会话（见 `event_bus._sibling_session`），因此拿到的是工厂
# 而不是现成的会话。


@dataclass(frozen=True)
class _FocusSpec:
    """一条订阅落下的记录长什么样：类型、等级从哪来、理由怎么拼。"""

    focus_type: str
    severity: Callable[[Mapping[str, Any]], str | None]
    reason: Callable[[Mapping[str, Any]], str]


def _alert_level(payload: Mapping[str, Any]) -> str | None:
    level = str(payload.get("alert_level") or "")
    return level or None


_RISK_ALERT_FOCUS = _FocusSpec(
    focus_type=risk_focus.FOCUS_RISK_ALERT,
    severity=_alert_level,
    reason=risk_focus.alert_reason,
)

# 意图没有等级：它是一次观察，不是按阈值判出的分级事实。
_RISK_INTENT_FOCUS = _FocusSpec(
    focus_type=risk_focus.FOCUS_RISK_INTENT,
    severity=lambda _payload: None,
    reason=risk_focus.intent_reason,
)


def _focus_handler(session_factory: SessionFactory, spec: _FocusSpec) -> Callable[[Event], None]:
    def handle(event: Event) -> None:
        payload = event.payload
        with session_factory() as db:
            risk_focus.record(
                db,
                customer_id=int(payload["customer_id"]),
                focus_type=spec.focus_type,
                severity=spec.severity(payload),
                reason=spec.reason(payload),
                source=event.source,
                trace_id=event.trace_id,
                occurred_at=event.occurred_at,
            )

    return handle


def build_subscriptions(session_factory: SessionFactory) -> Subscriptions:
    """当前的两条协作。新增订阅在这里加一条，发布方一行都不用改。"""
    return Subscriptions(
        Subscription(
            event_type=EVENT_RISK_ALERT_RAISED,
            name="advisory.risk_focus",
            handle=_focus_handler(session_factory, _RISK_ALERT_FOCUS),
        ),
        Subscription(
            event_type=EVENT_RISK_INTENT_DETECTED,
            name="risk_monitoring.risk_focus",
            handle=_focus_handler(session_factory, _RISK_INTENT_FOCUS),
        ),
    )
