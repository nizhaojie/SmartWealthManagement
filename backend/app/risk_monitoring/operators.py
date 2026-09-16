"""封闭的算子集合。

规则数据只能引用这里列出的算子。两种形状覆盖了反洗钱场景需要的判定：

- 单笔比较：拿本笔交易上某个字段的值直接与阈值比（大于、小于、区间）
- 聚合比较：拿时间窗内或同一自然日内该字段的取值做聚合（计数、求和、最大值、
  去重计数）后再与阈值比

集合是**有限且封闭**的：新增一种判定方式要改代码，并且要改数据库 CHECK 约束
（那边列的是同一份清单）。所以规则作者能配的只有算子支持的形状，规则数据无法
表达任意逻辑——否则它就是存在数据库里的代码，既不可测也不可审。

每个算子的语义只写在 `OPERATOR_REGISTRY` 里它的那一行：比什么、怎么聚合、阈值
要哪几个键。加一个算子是往这张表加一行，不是往五处 `if` 里各补一个分支。

集合是「可以这样判」的完整清单，不等于「每条规则都用得上」——20 条规则用其中
一部分，剩下的是规则作者调整时可选的形状。

**求值链路不经过模型。** 这里面全是数值比较与聚合，没有一处调用语言模型。「这笔
交易是否超过五万元」是确定性的数值比较，交给模型就变成一次概率性推断，比错一次
就是一次漏报。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

GT = "gt"
GTE = "gte"
LT = "lt"
LTE = "lte"
EQ = "eq"
NE = "ne"
BETWEEN = "between"
OUTSIDE = "outside"

WINDOW_COUNT_GTE = "window_count_gte"
WINDOW_SUM_GTE = "window_sum_gte"
WINDOW_MAX_GTE = "window_max_gte"
WINDOW_DISTINCT_COUNT_GTE = "window_distinct_count_gte"

DAILY_COUNT_GTE = "daily_count_gte"
DAILY_SUM_GTE = "daily_sum_gte"

SCOPE_SINGLE = "single"
SCOPE_WINDOW = "window"
SCOPE_DAILY = "daily"

RANGE_OPERATORS = (BETWEEN, OUTSIDE)
WINDOW_OPERATORS = (
    WINDOW_COUNT_GTE,
    WINDOW_SUM_GTE,
    WINDOW_MAX_GTE,
    WINDOW_DISTINCT_COUNT_GTE,
)
DAILY_OPERATORS = (DAILY_COUNT_GTE, DAILY_SUM_GTE)


class UnknownOperatorError(ValueError):
    pass


class InvalidThresholdError(ValueError):
    pass


# ---------------- 比较 ----------------


def _gt(left: Any, threshold: Mapping[str, Any]) -> bool:
    return left > threshold["value"]


def _gte(left: Any, threshold: Mapping[str, Any]) -> bool:
    return left >= threshold["value"]


def _lt(left: Any, threshold: Mapping[str, Any]) -> bool:
    return left < threshold["value"]


def _lte(left: Any, threshold: Mapping[str, Any]) -> bool:
    return left <= threshold["value"]


def _eq(left: Any, threshold: Mapping[str, Any]) -> bool:
    return left == threshold["value"]


def _ne(left: Any, threshold: Mapping[str, Any]) -> bool:
    return left != threshold["value"]


def _between(left: Any, threshold: Mapping[str, Any]) -> bool:
    return threshold["min"] <= left <= threshold["max"]


def _outside(left: Any, threshold: Mapping[str, Any]) -> bool:
    return left < threshold["min"] or left > threshold["max"]


# ---------------- 聚合 ----------------


def _count(values: tuple[Any, ...]) -> int:
    return len(values)


def _total(values: tuple[Any, ...]) -> Decimal:
    return sum((Decimal(str(value)) for value in values), Decimal("0"))


def _maximum(values: tuple[Any, ...]) -> Decimal:
    return max(Decimal(str(value)) for value in values)


def _distinct_count(values: tuple[Any, ...]) -> int:
    return len({str(value) for value in values})


@dataclass(frozen=True)
class OperatorSpec:
    """一个算子的全部语义。

    `compare` 拿观测值与归一化阈值比；`aggregate` 只给聚合算子，作用在时间窗
    （或自然日）内该字段有取值的所有事件上。
    """

    key: str
    label: str
    symbol: str
    compare: Callable[[Any, Mapping[str, Any]], bool]
    scope: str = SCOPE_SINGLE
    threshold_keys: tuple[str, ...] = ("value",)
    measure: str = ""
    aggregate: Callable[[tuple[Any, ...]], Any] | None = None


OPERATOR_REGISTRY: dict[str, OperatorSpec] = {
    spec.key: spec
    for spec in (
        OperatorSpec(GT, "大于", ">", _gt),
        OperatorSpec(GTE, "大于等于", "≥", _gte),
        OperatorSpec(LT, "小于", "<", _lt),
        OperatorSpec(LTE, "小于等于", "≤", _lte),
        OperatorSpec(EQ, "等于", "=", _eq),
        OperatorSpec(NE, "不等于", "≠", _ne),
        OperatorSpec(BETWEEN, "落在区间内", "∈", _between, threshold_keys=("min", "max")),
        OperatorSpec(OUTSIDE, "落在区间外", "∉", _outside, threshold_keys=("min", "max")),
        OperatorSpec(
            WINDOW_COUNT_GTE,
            "时间窗内计数",
            "≥",
            _gte,
            scope=SCOPE_WINDOW,
            measure="的笔数",
            aggregate=_count,
        ),
        OperatorSpec(
            WINDOW_SUM_GTE,
            "时间窗内求和",
            "≥",
            _gte,
            scope=SCOPE_WINDOW,
            measure="合计",
            aggregate=_total,
        ),
        OperatorSpec(
            WINDOW_MAX_GTE,
            "时间窗内最大值",
            "≥",
            _gte,
            scope=SCOPE_WINDOW,
            measure="的最大值",
            aggregate=_maximum,
        ),
        OperatorSpec(
            WINDOW_DISTINCT_COUNT_GTE,
            "时间窗内去重计数",
            "≥",
            _gte,
            scope=SCOPE_WINDOW,
            measure="的去重数",
            aggregate=_distinct_count,
        ),
        OperatorSpec(
            DAILY_COUNT_GTE,
            "同日计数",
            "≥",
            _gte,
            scope=SCOPE_DAILY,
            measure="的笔数",
            aggregate=_count,
        ),
        OperatorSpec(
            DAILY_SUM_GTE,
            "同日求和",
            "≥",
            _gte,
            scope=SCOPE_DAILY,
            measure="合计",
            aggregate=_total,
        ),
    )
}

OPERATOR_KEYS: tuple[str, ...] = tuple(OPERATOR_REGISTRY)


def to_comparable(value: Any) -> Decimal | str:
    """把取值与阈值统一成可比较的形态。

    数值一律走 Decimal——金额本身是 Decimal，用浮点阈值比较会引入误差。非数值
    会保持字符串，由 `require_number` 在校验阶段就挡掉。
    """
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, str):
        try:
            return Decimal(value)
        except InvalidOperation:
            return value
    return str(value)


def _require_spec(operator: str) -> OperatorSpec:
    spec = OPERATOR_REGISTRY.get(operator)
    if spec is None:
        raise UnknownOperatorError(f"未知的规则算子：{operator}")
    return spec


def _require_number(value: Any, operator: str) -> Decimal:
    """阈值必须是数值。

    挡在写入侧而不是求值侧：一个写坏了的阈值如果进了库，下一次匹配就会在比较时
    抛异常，整笔交易的判定跟着失败。
    """
    comparable = to_comparable(value)
    if not isinstance(comparable, Decimal):
        raise InvalidThresholdError(f"算子 {operator} 的阈值必须是数值")
    return comparable


def normalize_threshold(operator: str, threshold: Mapping[str, Any]) -> dict[str, Any]:
    """按算子要求的形状校验并归一化阈值。

    形状错了就抛错：规则数据是配置，配置错了要当场说出来，不能静默当成不命中。
    """
    spec = _require_spec(operator)
    if not isinstance(threshold, Mapping):
        raise InvalidThresholdError(f"算子 {operator} 的阈值应为对象")

    normalized: dict[str, Any] = {}
    for key in spec.threshold_keys:
        if key not in threshold:
            raise InvalidThresholdError(f"算子 {operator} 的阈值缺少 {key}")
        normalized[key] = _require_number(threshold[key], operator)

    if operator in RANGE_OPERATORS and normalized["min"] > normalized["max"]:
        raise InvalidThresholdError(f"算子 {operator} 的区间下界大于上界")
    return normalized


def format_value(value: Any) -> str:
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    return str(value)


def format_threshold(operator: str, threshold: Mapping[str, Any]) -> str:
    """阈值的人类可读形式，用于命中依据与规则管理页。"""
    try:
        normalized = normalize_threshold(operator, threshold)
    except (UnknownOperatorError, InvalidThresholdError):
        return str(dict(threshold))
    if operator in RANGE_OPERATORS:
        return f"[{format_value(normalized['min'])}, {format_value(normalized['max'])}]"
    return format_value(normalized["value"])


def compare(operator: str, observed: Any, normalized: Mapping[str, Any]) -> bool:
    """拿观测值与归一化后的阈值做一次确定性比较。

    收 `normalized` 而不是原始阈值，是为了「校验一次、比较多次」时不必重复做类型
    转换——一笔交易要过 20 条规则。
    """
    return _require_spec(operator).compare(to_comparable(observed), normalized)


def aggregate(operator: str, values: tuple[Any, ...]) -> Any | None:
    """聚合算子作用在时间窗内该字段**有取值**的事件上。

    字段返回 None 表示这条规则对那笔交易不适用，不计入聚合。一条都不适用时返回
    None——不是「合计为零」，聚合没有输入就没有结论。
    """
    spec = _require_spec(operator)
    if spec.aggregate is None:
        raise UnknownOperatorError(f"算子 {operator} 不做聚合")
    present = tuple(value for value in values if value is not None)
    if not present:
        return None
    return spec.aggregate(present)
