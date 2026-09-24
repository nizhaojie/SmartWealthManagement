"""写入侧的判定形状校验：名录 → 搭配 → 值域。

规则是配置，配置错了要当场说出来。三档挡的都是**不会自己报错**的错：一条「各列都合法、
搭配却不成立」的规则被收下之后不会有任何异常——`field = product_id` 配 `operator = gt`
是拿一个产品标识去比数值（「产品 5 号比 3 号大」既不是监管口径，也没人说得清它筛掉了
什么），把时刻、比例或等级差加起来得到的数同样没有含义。它们只会安静地留在库里：永远
不命中，或者命中得莫名其妙，而列表上看不出是哪一种。求值侧的另一类故障——阈值类型与
取值对不上，`operators._require_number` 与 `_gt` 两处注释说的正是它——也挡在这里，因为
它一旦进库，下一次匹配就是整笔交易的判定失败。

写入侧有且只有这一个入口，三档按顺序执行，谁先失败就报谁，每条消息都说清是哪一档、
哪个字段（不是一句「阈值与算子不匹配」）：

1. **名录**：`category` / `field` / `operator` / `alert_level` 必须落在各自的封闭清单里
   （`rules.RULE_CATEGORIES`、`fields.FIELD_REGISTRY`、`operators.OPERATOR_REGISTRY`、
   这里的 `ALERT_LEVELS`）。
2. **搭配**：`(field, operator)` 必须落在字段声明的 `allowed_operators` 里。
3. **值域**：阈值必须落在该字段声明的 `value_range` 里。

阈值的形状不在这里重写：`operators.normalize_threshold` 是求值侧同一份实现，这里只调
它、把它的说明带进消息。**形状排在值域之前**——值域要拿数值比，形状没定下来就无从比。
三档的次序（名录 → 搭配 → 值域）不变。

这一层是 ADR-0026 的执行机制，不是可选的好习惯；它挡住的是「配出一条下一笔交易就会炸、
或者永远不会命中的规则」。前端也读同一份契约（`GET /api/internal/risk-rules/schema`）：
schema 列出的允许算子就是这里收下的那些，同一份来源。前端禁掉的选项与这里拒掉的组合
一旦漂移，表现是「下拉里能选、一提交被拒」——不会有断言失败，只会有人反复试。

规则名称与权重不属于判定形状，也放在这一处挡：名称去空白后不能为空，权重必须落在可写
区间内。它们错了不会让规则永远不命中，但同样只有在这里才会被说清楚——「名称 200 个字」
与「权重 9」都该当场返回，而不是等数据库用列宽与精度把话说了。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.exceptions import AppError
from app.risk_monitoring.fields import FIELD_KEYS, FIELD_REGISTRY, ValueRange
from app.risk_monitoring.grading import LEVEL_LIGHT, LEVEL_MODERATE, LEVEL_SEVERE
from app.risk_monitoring.operators import (
    OPERATOR_KEYS,
    OPERATOR_REGISTRY,
    SCOPE_WINDOW,
    InvalidThresholdError,
    UnknownOperatorError,
    format_value,
    normalize_threshold,
    to_comparable,
)
from app.risk_monitoring.rules import RULE_CATEGORIES

# 预警等级的封闭清单：与 `fin_risk_rule.alert_level` 的 CHECK 约束、`grading` 里那三个
# 标签是同一份。它不参与分级（分级看命中条数与历史），但它是规则自身的必选项。
ALERT_LEVELS: tuple[str, ...] = (LEVEL_LIGHT, LEVEL_MODERATE, LEVEL_SEVERE)

# 规则名称的列宽（`fin_risk_rule.rule_name` 是 `String(128)`）：超了当场返回，不让 MySQL
# 去截断或报错。
RULE_NAME_MAX_LENGTH = 128

# 规则权重的默认值与可写区间（spec 的参数清单：可填，默认 1.00，区间 [0.50, 5.00]）。
# 权重不参与分级、也不决定是否命中，但它进置信度与「归到哪个规则分类」的判断——区间外的
# 值会让那两处都说不清。列是 `Numeric(5, 2)`，取值按两位小数归一，与库里存下的同一个数。
WEIGHT_DEFAULT = Decimal("1.00")
WEIGHT_QUANTUM = Decimal("0.01")
WEIGHT_RANGE = ValueRange(lower=Decimal("0.50"), upper=Decimal("5.00"))

BAD_REQUEST = 400


@dataclass(frozen=True)
class RuleShape:
    """一次写入通过校验后的判定形状：阈值已归一化，时间窗已按算子取舍。"""

    field: str
    operator: str
    threshold: dict[str, Any]
    window_hours: int | None


def validate_rule_definition(
    *,
    category: str,
    field: str,
    operator: str,
    alert_level: str,
    threshold: Mapping[str, Any],
    window_hours: int | None = None,
) -> RuleShape:
    """创建一条规则时的完整校验：名录 → 搭配 → 值域，外加时间窗与算子的一致性。

    名单里的每一个值都由后端说了算：前端下拉里能选什么，就是这里的清单。
    """
    normalize_category(category)
    _require_in_registry(field, FIELD_KEYS, "规则字段")
    _require_in_registry(operator, OPERATOR_KEYS, "规则算子")
    normalize_alert_level(alert_level)
    return RuleShape(
        field=field,
        operator=operator,
        threshold=validate_rule_shape(field=field, operator=operator, threshold=threshold),
        window_hours=_effective_window_hours(operator, window_hours),
    )


def validate_rule_shape(
    *, field: str, operator: str, threshold: Mapping[str, Any]
) -> dict[str, Any]:
    """校验一条规则的判定形状（搭配 → 形状 → 值域），返回归一化后的阈值。

    名录那一档由 `validate_rule_definition` 走在前面（改阈值时字段与算子是这条规则既有的，
    入库前已经过了名录校验）；字段那一列在这里再挡一次，是为了让这个入口单独调用时也
    报得出同一档的话，而不是一个 KeyError。
    """
    _require_in_registry(field, FIELD_KEYS, "规则字段")
    allowed = FIELD_REGISTRY[field].allowed_operators
    if operator not in allowed:
        raise AppError(
            BAD_REQUEST,
            f"搭配校验未通过：字段 {field} 不允许使用算子 {operator}"
            f"（该字段可配：{'、'.join(allowed)}）",
        )
    normalized = _normalize_threshold(operator, threshold)
    _require_in_value_range(field, normalized)
    return normalized


def normalize_category(category: str) -> str:
    """规则分类必须落在 `RULE_CATEGORIES` 里（库里的 CHECK 是同一份清单）。

    「创建」与「修改基本信息」两个入口都走它：分类在两个入口上读同一份清单、报同一句
    话，专员不会因为换了入口就看到两种口径。
    """
    _require_in_registry(category, RULE_CATEGORIES, "规则分类")
    return category


def normalize_alert_level(alert_level: str) -> str:
    """预警等级必须落在三个等级里；同样供创建与修改两个入口复用。"""
    _require_in_registry(alert_level, ALERT_LEVELS, "预警等级")
    return alert_level


def normalize_rule_name(rule_name: str) -> str:
    """规则名称的去空白形态；空的不收，超过列宽的也不收。

    「去空白后非空」而不是「非空」：一串空格在界面上与空标题没有区别，落库之后才会在
    列表里显示成一条没有名字的规则。
    """
    checked = (rule_name or "").strip()
    if not checked:
        raise AppError(BAD_REQUEST, "规则名称不能为空")
    if len(checked) > RULE_NAME_MAX_LENGTH:
        raise AppError(BAD_REQUEST, f"规则名称不能超过 {RULE_NAME_MAX_LENGTH} 字")
    return checked


def normalize_weight(weight: Any) -> Decimal:
    """规则权重：不给按 1.00，给了就必须落在 [0.50, 5.00] 内（spec 的参数清单）。

    数值的接受范围与阈值一致（字符串、整数、浮点都收，非数值一律拒），走的是求值侧
    同一份 `to_comparable`——「权重 1.5」与「权重 "1.5"」在这里是同一个数。

    `None` 等同「没给」：创建时它是「用默认值」，而不是「权重为空」——列非空，空白没有
    意义。取值按两位小数归一，与 `Numeric(5, 2)` 存进去的那个数是同一个，否则留痕快照
    会记下一个库里并不存在的数（0.505 落库成 0.51）。
    """
    if weight is None:
        return WEIGHT_DEFAULT
    comparable = to_comparable(weight)
    if not isinstance(comparable, Decimal):
        raise AppError(BAD_REQUEST, f"规则权重必须是数值：{weight}")
    if not WEIGHT_RANGE.contains(comparable):
        raise AppError(
            BAD_REQUEST,
            f"规则权重 {format_value(comparable)} 不在 {WEIGHT_RANGE.describe()} 内",
        )
    return comparable.quantize(WEIGHT_QUANTUM, rounding=ROUND_HALF_UP)


def _require_in_registry(value: str, allowed: tuple[str, ...], label: str) -> None:
    if value not in allowed:
        raise AppError(BAD_REQUEST, f"名录校验未通过：{label}不在允许清单内：{value}")


def _normalize_threshold(operator: str, threshold: Mapping[str, Any]) -> dict[str, Any]:
    """形状交给求值侧同一份实现，只把它的说明带进消息。

    一句「阈值与算子不匹配」说不清是哪个键写错了，而写错的那个键正是专员需要知道的。
    """
    try:
        return normalize_threshold(operator, threshold)
    except (UnknownOperatorError, InvalidThresholdError) as exc:
        raise AppError(BAD_REQUEST, f"阈值形状校验未通过：{exc}") from exc


def _require_in_value_range(field: str, normalized: Mapping[str, Any]) -> None:
    """阈值必须落在字段声明的值域内。

    对聚合算子这条检查是**保守**的：它比的是阈值与字段取值的物理边界，而聚合出来的量
    （笔数、合计）与字段取值不同量纲。宁可拒掉几个语义上成立的阈值，也不放一条永远不
    命中的规则进来——前者专员当场就能看懂，后者不会有任何提示。
    """
    value_range = FIELD_REGISTRY[field].value_range
    if value_range is None:
        return
    for value in normalized.values():
        if isinstance(value, Decimal) and not value_range.contains(value):
            raise AppError(
                BAD_REQUEST,
                f"值域校验未通过：字段 {field} 的阈值 {format_value(value)}"
                f" 不在 {value_range.describe()} 内",
            )


def _effective_window_hours(operator: str, window_hours: int | None) -> int | None:
    """时间窗算子必须给正整数窗长；其余算子一律置空。

    非时间窗算子带窗长不是错误，是多余——它与算子无关，落库前丢掉，而不是在库里留一个
    读不懂的字段（spec 的参数清单：其余算子提交时置 NULL）。
    """
    if OPERATOR_REGISTRY[operator].scope != SCOPE_WINDOW:
        return None
    if isinstance(window_hours, bool) or not isinstance(window_hours, int) or window_hours <= 0:
        raise AppError(
            BAD_REQUEST,
            f"时间窗校验未通过：算子 {operator} 需要正整数的小时窗（window_hours）",
        )
    return window_hours
