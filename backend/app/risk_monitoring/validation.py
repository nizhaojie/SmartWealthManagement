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
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.exceptions import AppError
from app.risk_monitoring.fields import FIELD_KEYS, FIELD_REGISTRY
from app.risk_monitoring.grading import LEVEL_LIGHT, LEVEL_MODERATE, LEVEL_SEVERE
from app.risk_monitoring.operators import (
    OPERATOR_KEYS,
    OPERATOR_REGISTRY,
    SCOPE_WINDOW,
    InvalidThresholdError,
    UnknownOperatorError,
    format_value,
    normalize_threshold,
)
from app.risk_monitoring.rules import RULE_CATEGORIES

# 预警等级的封闭清单：与 `fin_risk_rule.alert_level` 的 CHECK 约束、`grading` 里那三个
# 标签是同一份。它不参与分级（分级看命中条数与历史），但它是规则自身的必选项。
ALERT_LEVELS: tuple[str, ...] = (LEVEL_LIGHT, LEVEL_MODERATE, LEVEL_SEVERE)

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
    _require_in_registry(category, RULE_CATEGORIES, "规则分类")
    _require_in_registry(field, FIELD_KEYS, "规则字段")
    _require_in_registry(operator, OPERATOR_KEYS, "规则算子")
    _require_in_registry(alert_level, ALERT_LEVELS, "预警等级")
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
