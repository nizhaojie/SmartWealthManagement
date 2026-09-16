"""规则求值：输入一笔交易与一条规则，输出是否命中。

这是一个纯函数——没有数据库、没有网络、没有模型调用、也不读系统时钟。输入的
`MonitoringContext` 里带着本笔交易事件与该客户在此之前的事件，时间窗与自然日都
以本笔事件的 `occurred_at` 为基准回溯（与 ADR-0011 同源的取舍：基准从外面传进来，
函数内部不读时钟，于是「恰好在窗口边界上算不算」可以写成一个直接断言的用例）。

阈值判断的任何环节都不经过模型。模型只在预警产生之后参与，把结构化的命中结果
讲成人话。
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import timedelta

from app.risk_monitoring.context import MonitoringContext, RuleHit, RuleSpec, TransactionEvent
from app.risk_monitoring.fields import FIELD_REGISTRY
from app.risk_monitoring.operators import (
    OPERATOR_REGISTRY,
    SCOPE_DAILY,
    SCOPE_SINGLE,
    SCOPE_WINDOW,
    aggregate,
    compare,
    format_threshold,
    format_value,
    normalize_threshold,
)

UNKNOWN_FIELD_MESSAGE = "未知的规则字段"
MISSING_WINDOW_MESSAGE = "时间窗算子缺少窗长"


def _events_in_window(
    context: MonitoringContext, window_hours: int
) -> tuple[TransactionEvent, ...]:
    """时间窗内的事件：以本笔事件为终点向前回溯 `window_hours` 小时，含本笔。"""
    start = context.event.occurred_at - timedelta(hours=window_hours)
    end = context.event.occurred_at
    return tuple(
        event
        for event in (*context.history, context.event)
        if start <= event.occurred_at <= end
    )


def _events_same_day(context: MonitoringContext) -> tuple[TransactionEvent, ...]:
    day = context.event.occurred_at.date()
    return tuple(
        event for event in (*context.history, context.event) if event.occurred_at.date() == day
    )


def _scope_text(scope: str, window_hours: int | None) -> str:
    if scope == SCOPE_DAILY:
        return "同日"
    if scope == SCOPE_WINDOW:
        return f"{window_hours} 小时内"
    return ""


def evaluate_rule(rule: RuleSpec, context: MonitoringContext) -> RuleHit | None:
    """对一条规则求值。命中返回 `RuleHit`，未命中或不适用返回 None。

    三种「不命中」要分清楚：值确实没到阈值；字段对本笔交易不适用（比如赎回
    规则遇到申购）；规则被停用。它们对外都是 None，但原因不同。
    """
    field_spec = FIELD_REGISTRY.get(rule.field)
    if field_spec is None:
        raise ValueError(f"{UNKNOWN_FIELD_MESSAGE}：{rule.field}")
    operator_spec = OPERATOR_REGISTRY.get(rule.operator)
    if operator_spec is None:
        raise ValueError(f"未知的规则算子：{rule.operator}")

    if not rule.enabled:
        return None

    threshold = normalize_threshold(rule.operator, rule.threshold)
    threshold_text = format_threshold(rule.operator, rule.threshold)

    if operator_spec.scope == SCOPE_SINGLE:
        observed = field_spec.extract(context, context.event)
    else:
        if operator_spec.scope == SCOPE_WINDOW:
            if rule.window_hours is None:
                raise ValueError(MISSING_WINDOW_MESSAGE)
            events = _events_in_window(context, rule.window_hours)
        else:
            events = _events_same_day(context)
        observed = aggregate(
            rule.operator, tuple(field_spec.extract(context, event) for event in events)
        )

    if observed is None or not compare(rule.operator, observed, threshold):
        return None

    return RuleHit(
        rule_code=rule.rule_code,
        rule_name=rule.rule_name,
        category=rule.category,
        alert_level=rule.alert_level,
        weight=rule.weight,
        field=rule.field,
        field_label=field_spec.label,
        operator=rule.operator,
        threshold=threshold_text,
        observed_value=format_value(observed),
        evidence=(
            f"{_scope_text(operator_spec.scope, rule.window_hours)}"
            f"{field_spec.label}{operator_spec.measure} {format_value(observed)}"
            f" {operator_spec.symbol} 阈值 {threshold_text}"
        ),
    )


def match_rules(rules: Iterable[RuleSpec], context: MonitoringContext) -> list[RuleHit]:
    """逐条匹配，返回命中的规则；停用的规则不参与。"""
    return [hit for rule in rules if (hit := evaluate_rule(rule, context)) is not None]
