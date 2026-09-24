"""可判定的字段集合。

字段和算子一样是封闭的：规则数据只能从 `FIELD_REGISTRY` 的键里挑一个，库里
还有一条 CHECK 约束守着同一份清单。

字段背后是代码，所以「距同产品最近一次反向交易多久」「金额是否贴着申报阈值」
这类复合语义写在代码里，而不是让规则作者用数据拼出来。规则数据一旦能拼逻辑，
它就是存在数据库里的代码——既不可测也不可审。

取值函数的第二个参数是「被判定的那一笔」：单笔比较时它是本笔事件，时间窗聚合
时它是窗内的每一笔。`context.history` 始终是本笔之前的事件，取值时再按时间截
断，于是同一个字段在两种用法下语义一致。

每个字段除取值函数外还声明两件事，与它写在同一行里：

- `allowed_operators`：这个字段允许配哪些算子（写入侧第二档校验）。一份「字段 ×
  算子」的允许矩阵因此就是这张注册表本身——加一种可配的组合是改那一行，不是在
  `if` 里补一个分支。取值不是数值的字段（`product_id` 是产品标识）只允许不去比
  数值的算子；取值语义是小时、百分比或等级差的字段不允许求和类聚合——把时刻、
  比例、等级差加起来得到的数没有任何含义。
- `value_range`：阈值的物理值域（写入侧第三档校验），同时也下发给前端。

两处声明都只写在这里：写入侧拿它们拒绝，`GET /api/internal/risk-rules/schema` 拿
它们下发给前端，**不是两份互相抄的清单**（ADR-0026）。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.risk_monitoring.context import MonitoringContext, TransactionEvent
from app.risk_monitoring.operators import (
    BETWEEN,
    DAILY_COUNT_GTE,
    DAILY_SUM_GTE,
    EQ,
    GT,
    GTE,
    LT,
    LTE,
    NE,
    OUTSIDE,
    WINDOW_COUNT_GTE,
    WINDOW_DISTINCT_COUNT_GTE,
    WINDOW_MAX_GTE,
    WINDOW_SUM_GTE,
)

PURCHASE = "申购"
REDEEM = "赎回"
OPPOSITE_TRANSACTION_TYPES = {PURCHASE: REDEEM, REDEEM: PURCHASE}

# 大额交易申报阈值是法定口径（人民币 5 万元），不是规则里的可配参数。
# 「贴着阈值走」的识别区间因此也是固定的：金额的 [90%, 100%)。
LARGE_AMOUNT_REPORTING_THRESHOLD = Decimal("50000")
THRESHOLD_AVOIDANCE_RATIO = Decimal("0.9")

# 小额与整数化大额是两条用于识别拆分的固定口径。
SMALL_AMOUNT_LIMIT = Decimal("10000")
ROUND_AMOUNT_UNIT = Decimal("10000")
ROUND_AMOUNT_MIN = Decimal("100000")

FieldValue = Decimal | int | str | None
Extractor = Callable[[MonitoringContext, TransactionEvent], FieldValue]

# 字段键做成常量：规则定义、数据库 CHECK 约束与测试引用的是同一批名字，
# 拼错了要在导入时就炸，而不是等到某条规则永远不命中。
FIELD_AMOUNT = "amount"
FIELD_PURCHASE_AMOUNT = "purchase_amount"
FIELD_REDEEM_AMOUNT = "redeem_amount"
FIELD_HOUR_OF_DAY = "hour_of_day"
FIELD_AMOUNT_TO_ASSETS_RATIO = "amount_to_assets_ratio"
FIELD_RISK_LEVEL_GAP = "risk_level_gap"
FIELD_REVERSE_INTERVAL_HOURS = "reverse_interval_hours"
FIELD_THRESHOLD_AVOIDANCE_AMOUNT = "threshold_avoidance_amount"
FIELD_SMALL_AMOUNT = "small_amount"
FIELD_LARGE_ROUND_AMOUNT = "large_round_amount"
FIELD_PRODUCT_ID = "product_id"


@dataclass(frozen=True)
class ValueRange:
    """阈值的物理值域：这个字段的阈值允许落在哪里。

    声明在字段上而不是散在阈值校验的 `if` 里：写入侧拿它拒绝越界阈值，schema 端点拿
    它告诉前端这个字段的阈值最多到哪，两处读的是同一份声明。两侧都可以不设限
    （`lower` / `upper` 为 None），只有确实有物理边界的字段才两边都写。
    """

    lower: Decimal | None = None
    upper: Decimal | None = None
    lower_inclusive: bool = True
    upper_inclusive: bool = True

    def contains(self, value: Decimal) -> bool:
        if self.lower is not None and (
            value < self.lower or (value == self.lower and not self.lower_inclusive)
        ):
            return False
        if self.upper is not None and (
            value > self.upper or (value == self.upper and not self.upper_inclusive)
        ):
            return False
        return True

    def describe(self) -> str:
        """值域的人类可读形式：校验失败的消息与界面提示都直接用这一句。"""
        bounds: list[str] = []
        if self.lower is not None:
            bounds.append(f"{'≥' if self.lower_inclusive else '>'} {_number_text(self.lower)}")
        if self.upper is not None:
            bounds.append(f"{'≤' if self.upper_inclusive else '<'} {_number_text(self.upper)}")
        return " 且 ".join(bounds)

    def as_payload(self) -> dict[str, Any]:
        """给前端的形态：两端、端点是否含，外加一句可以直接展示的文本。"""
        return {
            "min": _number_text(self.lower) if self.lower is not None else None,
            "max": _number_text(self.upper) if self.upper is not None else None,
            "min_inclusive": self.lower_inclusive,
            "max_inclusive": self.upper_inclusive,
            "text": self.describe(),
        }


def _number_text(value: Decimal) -> str:
    """数值的展示形态：`50.00` 写成 `50`，与求值侧 `format_value` 同一口径。"""
    return format(value.normalize(), "f")


# ---------------- 字段 × 算子的允许矩阵 ----------------

# 比较类：拿取值直接与阈值比。数值字段都能配，`product_id` 不能——它的取值是产品标识，
# 阈值却被归一化成 Decimal，拿去比会在求值那一刻抛 TypeError，整笔交易的判定跟着失败。
COMPARISON_OPERATORS: tuple[str, ...] = (GT, GTE, LT, LTE, EQ, NE, BETWEEN, OUTSIDE)

# 不做加法的聚合：数笔数、去重数、比大小。它们要么整笔不用取值，要么只用大小关系。
NON_SUM_AGGREGATE_OPERATORS: tuple[str, ...] = (
    WINDOW_COUNT_GTE,
    WINDOW_MAX_GTE,
    WINDOW_DISTINCT_COUNT_GTE,
    DAILY_COUNT_GTE,
)

# 求和类聚合：把时间窗（或自然日）内的取值加起来。只对「加起来有意义」的字段开放。
SUM_AGGREGATE_OPERATORS: tuple[str, ...] = (WINDOW_SUM_GTE, DAILY_SUM_GTE)

# 金额类字段：四种比较加两类聚合都给——合计多少、最大多少、几笔、几种，都是金额上的问题。
MONEY_FIELD_OPERATORS: tuple[str, ...] = (
    COMPARISON_OPERATORS + NON_SUM_AGGREGATE_OPERATORS + SUM_AGGREGATE_OPERATORS
)

# 不是金额的数值字段：小时、百分比、等级差。能比、能数，但**不允许求和**——把这些值
# 加起来得到的数没有含义，那种规则配出来只会是永远不命中，或者口径没人说得清。
NON_ADDITIVE_OPERATORS: tuple[str, ...] = COMPARISON_OPERATORS + NON_SUM_AGGREGATE_OPERATORS

# 金额的值域：正的金额，上界不设——金额本身没有物理上限，不同规则的阈值可以落在任何
# 正的金额上。下界开区间：阈值 0 的金额规则（「金额 > 0」）等于不筛，不是一条规则。
POSITIVE_AMOUNT_RANGE: ValueRange = ValueRange(lower=Decimal("0"), lower_inclusive=False)


def _amount(_context: MonitoringContext, event: TransactionEvent) -> FieldValue:
    return event.amount


def _typed_amount(transaction_type: str) -> Extractor:
    def extract(_context: MonitoringContext, event: TransactionEvent) -> FieldValue:
        if event.transaction_type != transaction_type:
            return None
        return event.amount

    return extract


def _hour_of_day(_context: MonitoringContext, event: TransactionEvent) -> FieldValue:
    return event.occurred_at.hour


def _amount_to_assets_ratio(context: MonitoringContext, event: TransactionEvent) -> FieldValue:
    total_assets = context.customer.total_assets
    if total_assets is None or total_assets <= 0:
        return None
    ratio = event.amount / total_assets * Decimal("100")
    return ratio.quantize(Decimal("0.0001"))


def _grade_number(value: str | None, prefix: str) -> int | None:
    """把规范写法的等级（C1 到 C5、R1 到 R5）折成用于比较的序数。

    写进上下文的是规范取值而不是裸整数：C1 到 C5 与 R1 到 R5 是 CONTEXT 里的唯一
    写法，折算是求值的事，不该让调用方先自己算一遍。
    """
    if not value or len(value) != 2 or value[0] != prefix or not value[1].isdigit():
        return None
    return int(value[1])


def _risk_level_gap(context: MonitoringContext, _event: TransactionEvent) -> FieldValue:
    """产品风险等级减去风险承受等级：正值表示越级，缺任一侧时不适用。"""
    product = _grade_number(context.product_risk_level, "R")
    customer = _grade_number(context.customer.risk_level, "C")
    if product is None or customer is None:
        return None
    return product - customer


def _reverse_interval_hours(context: MonitoringContext, event: TransactionEvent) -> FieldValue:
    """被判定这笔与同产品上最近一次**反向**交易的间隔（小时）。

    没有反向交易时返回 None：规则不适用，而不是间隔无穷大。只在该笔之前的事件
    里找——未来的反向交易不能用来解释现在这笔。
    """
    opposite = OPPOSITE_TRANSACTION_TYPES.get(event.transaction_type)
    if opposite is None or event.product_id is None:
        return None
    candidates = [
        past
        for past in context.history
        if past.occurred_at < event.occurred_at
        and past.product_id == event.product_id
        and past.transaction_type == opposite
    ]
    if not candidates:
        return None
    latest = max(candidates, key=lambda item: item.occurred_at)
    hours = (event.occurred_at - latest.occurred_at).total_seconds() / 3600
    return Decimal(str(round(hours, 4)))


def _threshold_avoidance_amount(
    _context: MonitoringContext, event: TransactionEvent
) -> FieldValue:
    """金额落在大额申报阈值 [90%, 100%) 内时返回该金额，否则不适用。

    恰好卡在阈值之下是拆分的典型形态：单笔都不够申报标准，合起来远超。
    """
    amount = event.amount
    lower = LARGE_AMOUNT_REPORTING_THRESHOLD * THRESHOLD_AVOIDANCE_RATIO
    if lower <= amount < LARGE_AMOUNT_REPORTING_THRESHOLD:
        return amount
    return None


def _small_amount(_context: MonitoringContext, event: TransactionEvent) -> FieldValue:
    return event.amount if event.amount < SMALL_AMOUNT_LIMIT else None


def _large_round_amount(_context: MonitoringContext, event: TransactionEvent) -> FieldValue:
    """万元以上整数倍的大额金额。整数化往往是人为凑出来的金额。"""
    amount = event.amount
    if amount < ROUND_AMOUNT_MIN:
        return None
    return amount if amount % ROUND_AMOUNT_UNIT == 0 else None


def _product_id(_context: MonitoringContext, event: TransactionEvent) -> FieldValue:
    return event.product_id


@dataclass(frozen=True)
class FieldSpec:
    """一个字段的全部声明：怎么取值、能配哪些算子、阈值能落在哪。"""

    key: str
    label: str
    description: str
    extract: Extractor
    # 这个字段允许配的算子——「字段 × 算子」矩阵的其中一行（写入侧第二档）。
    allowed_operators: tuple[str, ...]
    # 阈值的物理值域（写入侧第三档）；None 表示这个字段没有数值值域可声明。
    value_range: ValueRange | None = None


FIELD_REGISTRY: dict[str, FieldSpec] = {
    spec.key: spec
    for spec in (
        FieldSpec(
            key=FIELD_AMOUNT,
            label="交易金额",
            description="本笔交易的成交金额",
            extract=_amount,
            allowed_operators=MONEY_FIELD_OPERATORS,
            value_range=POSITIVE_AMOUNT_RANGE,
        ),
        FieldSpec(
            key=FIELD_PURCHASE_AMOUNT,
            label="申购金额",
            description="本笔为申购时的金额；其他交易类型不适用",
            extract=_typed_amount(PURCHASE),
            allowed_operators=MONEY_FIELD_OPERATORS,
            value_range=POSITIVE_AMOUNT_RANGE,
        ),
        FieldSpec(
            key=FIELD_REDEEM_AMOUNT,
            label="赎回金额",
            description="本笔为赎回时的金额；其他交易类型不适用",
            extract=_typed_amount(REDEEM),
            allowed_operators=MONEY_FIELD_OPERATORS,
            value_range=POSITIVE_AMOUNT_RANGE,
        ),
        FieldSpec(
            key=FIELD_HOUR_OF_DAY,
            label="交易发生时间（小时）",
            description="交易发生时刻的小时数，取值 0 到 23",
            extract=_hour_of_day,
            allowed_operators=NON_ADDITIVE_OPERATORS,
            # 时刻的物理边界：0 点到 23 点，两端都含。「24 点」在库里是 0 点。
            value_range=ValueRange(lower=Decimal("0"), upper=Decimal("23")),
        ),
        FieldSpec(
            key=FIELD_AMOUNT_TO_ASSETS_RATIO,
            label="单笔金额占客户总资产比例",
            description="金额占客户画像总资产的百分比；无画像时不适用",
            extract=_amount_to_assets_ratio,
            allowed_operators=NON_ADDITIVE_OPERATORS,
            # 比例是正的；上界不设——一笔交易的金额可以远超客户的总资产。
            value_range=ValueRange(lower=Decimal("0"), lower_inclusive=False),
        ),
        FieldSpec(
            key=FIELD_RISK_LEVEL_GAP,
            label="产品风险等级与风险承受等级之差",
            description="产品风险等级减去客户风险承受等级，正值表示越级；缺任一侧时不适用",
            extract=_risk_level_gap,
            allowed_operators=NON_ADDITIVE_OPERATORS,
            # 等级是 C1–C5 与 R1–R5，折算成序数后差值的物理边界是 -4 到 4。
            value_range=ValueRange(lower=Decimal("-4"), upper=Decimal("4")),
        ),
        FieldSpec(
            key=FIELD_REVERSE_INTERVAL_HOURS,
            label="同产品反向交易间隔",
            description="与同一产品上最近一次反向交易的间隔小时数；无反向交易时不适用",
            extract=_reverse_interval_hours,
            allowed_operators=NON_ADDITIVE_OPERATORS,
            # 间隔是正的；「间隔 < 0 小时」这种规则永远不会命中。
            value_range=ValueRange(lower=Decimal("0"), lower_inclusive=False),
        ),
        FieldSpec(
            key=FIELD_THRESHOLD_AVOIDANCE_AMOUNT,
            label="贴近大额申报阈值的金额",
            description="金额落在申报阈值九成至阈值之间时的金额，用于识别拆分",
            extract=_threshold_avoidance_amount,
            allowed_operators=MONEY_FIELD_OPERATORS,
            value_range=POSITIVE_AMOUNT_RANGE,
        ),
        FieldSpec(
            key=FIELD_SMALL_AMOUNT,
            label="小额交易金额",
            description="金额低于小额上限时的金额，用于识别化整为零",
            extract=_small_amount,
            allowed_operators=MONEY_FIELD_OPERATORS,
            value_range=POSITIVE_AMOUNT_RANGE,
        ),
        FieldSpec(
            key=FIELD_LARGE_ROUND_AMOUNT,
            label="整数倍大额金额",
            description="金额不低于整数化下限且为万元整数倍时的金额",
            extract=_large_round_amount,
            allowed_operators=MONEY_FIELD_OPERATORS,
            value_range=POSITIVE_AMOUNT_RANGE,
        ),
        FieldSpec(
            key=FIELD_PRODUCT_ID,
            label="产品标识",
            description="交易对应的产品标识",
            extract=_product_id,
            # 取值是产品标识而不是数：凡是要拿它比数值的算子（比较类与求和/最大值）都会
            # 在求值时抛错，去重计数是唯一用得上这个取值的算子。计数类的语义与字段无关
            # ——那等于在数交易笔数，该写在 `amount` 上。
            allowed_operators=(WINDOW_DISTINCT_COUNT_GTE,),
            # 产品标识本身没有数值值域；它那一个算子的阈值是去重后的产品数，不是字段取值。
        ),
    )
}

FIELD_KEYS: tuple[str, ...] = tuple(FIELD_REGISTRY)
