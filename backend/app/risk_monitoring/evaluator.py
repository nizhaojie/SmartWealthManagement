"""规则求值：输入一笔交易与一条规则，输出是否命中。

这是一个纯函数——没有数据库、没有网络、没有模型调用、也不读系统时钟。输入的
`MonitoringContext` 里带着本笔交易事件与该客户在此之前的事件，时间窗与自然日都
以本笔事件的 `occurred_at` 为基准回溯（与 ADR-0011 同源的取舍：基准从外面传进来，
函数内部不读时钟，于是「恰好在窗口边界上算不算」可以写成一个直接断言的用例）。

阈值判断的任何环节都不经过模型。模型只在预警产生之后参与，把结构化的命中结果
讲成人话。

一条判定形状的文字形态也在这里：命中依据（`evidence`）与规则描述（`rule_description`）
共用同一个主语函数，两者只差中间有没有观测值——「7 小时内交易金额的笔数 12 ≥ 阈值 10」
与「7 小时内交易金额的笔数 ≥ 阈值 10」。各写一套的话，规则管理页上的描述与预警里的依据
会是同一件事的两种说法。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import timedelta
from typing import Any

from app.risk_monitoring.context import MonitoringContext, RuleHit, RuleSpec, TransactionEvent
from app.risk_monitoring.fields import FIELD_REGISTRY, FieldSpec
from app.risk_monitoring.operators import (
    OPERATOR_REGISTRY,
    SCOPE_DAILY,
    SCOPE_SINGLE,
    SCOPE_WINDOW,
    OperatorSpec,
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


def _rule_subject(
    field_spec: FieldSpec, operator_spec: OperatorSpec, window_hours: int | None
) -> str:
    """一条判定形状的主语：作用域 + 字段标签 + 算子的量词。

    「7 小时内交易金额的笔数」「同日交易金额的合计」「交易金额」（单笔算子没有作用域，
    也没有量词）。命中依据与规则描述都从它开始拼。
    """
    return (
        f"{_scope_text(operator_spec.scope, window_hours)}"
        f"{field_spec.label}{operator_spec.measure}"
    )


def rule_description(
    *,
    field: str,
    operator: str,
    threshold: Mapping[str, Any],
    window_hours: int | None,
) -> str:
    """描述留空时自动生成的那句话：与 `evidence` 同一套词，只是没有观测值。

    例：「7 小时内交易金额的笔数 ≥ 阈值 10」。它描述的是规则**要什么条件**，不描述
    某一笔交易满足了多少——所以没有观测值那一格。
    """
    operator_spec = OPERATOR_REGISTRY[operator]
    return (
        f"{_rule_subject(FIELD_REGISTRY[field], operator_spec, window_hours)} "
        f"{operator_spec.symbol} 阈值 {format_threshold(operator, threshold)}"
    )


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
            f"{_rule_subject(field_spec, operator_spec, rule.window_hours)} "
            f"{format_value(observed)} {operator_spec.symbol} 阈值 {threshold_text}"
        ),
    )


def match_rules(rules: Iterable[RuleSpec], context: MonitoringContext) -> list[RuleHit]:
    """逐条匹配，返回命中的规则；停用的规则不参与。"""
    return [hit for rule in rules if (hit := evaluate_rule(rule, context)) is not None]
