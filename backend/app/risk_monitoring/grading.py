"""预警分级与置信度：确定性代码，不经过模型。

分级只看两件事，都是已经确定的事实：这笔交易命中了多少条规则，以及这位客户之前
有没有预警记录。同一个输入永远得到同一个等级——这是刻意的，风控的结论不该因为
一次模型调用而漂移。

置信度是另一回事。它是命中规则权重的折算结果，**只用于排序与分级展示**：
- 它不参与上面的分级（分级看条数与历史，不看分数）；
- 它不用于关闭预警——没有任何阈值能触发自动关闭。写在这里，因为「低置信自动
  关掉能减少工作量」是一个很容易被当作优化提出的想法，而它会让预警被系统悄悄
  消化掉。
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Decimal

from app.risk_monitoring.context import RuleHit

LEVEL_LIGHT = "轻度"
LEVEL_MODERATE = "中度"
LEVEL_SEVERE = "重度"

# 置信度的满分线：命中规则的权重合计达到这个值即记 1.00。权重由规则表给出，
# 因此「哪些规则叠加起来算证据充足」是可配的，折算方式是代码。
CONFIDENCE_FULL_SCORE = Decimal("10.00")
CONFIDENCE_QUANTUM = Decimal("0.01")
MAX_CONFIDENCE = Decimal("1.00")

ZERO = Decimal("0")


def grade_alert_level(hit_count: int, *, has_prior_alert: bool) -> str:
    """单条命中为轻度；多条交叉为中度；多条命中且该客户有历史预警记录为重度。

    `has_prior_alert` 由调用方查库得出，且必须是**本次预警之前**的记录——否则
    第一笔预警就会把自己算成历史，人人都是重度。
    """
    if hit_count <= 1:
        return LEVEL_LIGHT
    return LEVEL_SEVERE if has_prior_alert else LEVEL_MODERATE


def compute_confidence(hits: Iterable[RuleHit]) -> Decimal:
    """命中规则的权重合计按满分线折算到 0 到 1，两位小数。

    四舍五入而不是银行家舍入：这个数字要展示给风控专员看，0.125 显示成 0.12
    会让人以为折算方式比实际更保守。

    超过满分线记满分：到那一步的都是「证据非常充分」，它们之间的排序差异已经没有
    意义。封顶不会造成任何风险——置信度不参与分级，也不参与关闭判断，顶格与不满
    顶格的预警走同一条处置路径。
    """
    total = sum((hit.weight for hit in hits), ZERO)
    value = total / CONFIDENCE_FULL_SCORE
    if value > MAX_CONFIDENCE:
        value = MAX_CONFIDENCE
    return value.quantize(CONFIDENCE_QUANTUM, rounding=ROUND_HALF_UP)


def alert_type_for(hits: Iterable[RuleHit]) -> str:
    """预警类型：命中规则的分类中权重合计最高的那个。

    一条交易的命中可能横跨多个分类，取最重的那一类作为这条预警的类型——它回答
    「这笔交易主要是因为什么被标记的」。

    并列时取先出现的：`match_rules` 按规则编号顺序产出命中，因此并列的取编号靠前
    的分类，结果不随字典遍历顺序变化。
    """
    totals: dict[str, Decimal] = {}
    for hit in hits:
        totals[hit.category] = totals.get(hit.category, ZERO) + hit.weight
    if not totals:
        return ""
    return max(totals, key=lambda category: totals[category])


def render_trigger_detail(hits: Iterable[RuleHit]) -> str:
    """把命中依据拼成给风控专员看的多行文本：一行一条规则。

    每行都落到字段与值的粒度（「交易金额 520000 ≥ 阈值 50000」）而不只是规则名
    ——风控专员靠这个判断是不是误报。
    """
    return "\n".join(f"{hit.rule_name}（{hit.rule_code}）：{hit.evidence}" for hit in hits)
