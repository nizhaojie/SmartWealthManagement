"""20 条反洗钱可疑交易识别规则。

这是唯一的规则来源：`seed` 把它写进 `fin_risk_rule`，测试直接拿它构造用例。
规则在这里是数据——字段、运算符、阈值、预警等级、权重——没有任何一条把判定逻辑
写在自己身上，求值统一走 `evaluator.evaluate_rule`。

阈值判断不经过模型：改阈值改的是这张表，不是代码，也不是提示词。

`alert_level` 是规则自身的预警等级。它不等于「命中这条规则就一定产生该等级预警」
——预警的等级由命中条数与该客户的历史预警记录推导，那是另一段确定性代码。
"""

from __future__ import annotations

from decimal import Decimal

from app.risk_monitoring.context import RuleSpec
from app.risk_monitoring.fields import (
    FIELD_AMOUNT,
    FIELD_AMOUNT_TO_ASSETS_RATIO,
    FIELD_HOUR_OF_DAY,
    FIELD_LARGE_ROUND_AMOUNT,
    FIELD_PRODUCT_ID,
    FIELD_PURCHASE_AMOUNT,
    FIELD_REDEEM_AMOUNT,
    FIELD_REVERSE_INTERVAL_HOURS,
    FIELD_RISK_LEVEL_GAP,
    FIELD_SMALL_AMOUNT,
    FIELD_THRESHOLD_AVOIDANCE_AMOUNT,
)
from app.risk_monitoring.operators import (
    DAILY_COUNT_GTE,
    DAILY_SUM_GTE,
    GTE,
    LTE,
    OUTSIDE,
    WINDOW_COUNT_GTE,
    WINDOW_DISTINCT_COUNT_GTE,
    WINDOW_SUM_GTE,
)

HOUR = 1
DAY = 24
WEEK = 168
MONTH = 720

CATEGORY_LARGE_AMOUNT = "大额交易"
CATEGORY_FREQUENT = "频繁交易"
CATEGORY_QUICK_IN_OUT = "快进快出"
CATEGORY_SPLITTING = "拆分规避"
CATEGORY_ODD_HOURS = "异常时段"
CATEGORY_MISMATCH = "资产错配"
CATEGORY_SUITABILITY = "适当性"


def _rule(
    *,
    rule_code: str,
    rule_name: str,
    category: str,
    description: str,
    field: str,
    operator: str,
    threshold: dict,
    alert_level: str,
    weight: str,
    window_hours: int | None = None,
) -> RuleSpec:
    return RuleSpec(
        rule_code=rule_code,
        rule_name=rule_name,
        category=category,
        description=description,
        field=field,
        operator=operator,
        threshold=threshold,
        window_hours=window_hours,
        alert_level=alert_level,
        weight=Decimal(weight),
    )


# 阈值统一写成字符串：JSON 列存不下 Decimal，字符串在两个方向上都不会走浮点。
RISK_RULE_SEEDS: tuple[RuleSpec, ...] = (
    # ---------------- 大额交易 ----------------
    _rule(
        rule_code="R001",
        rule_name="单笔大额交易",
        category=CATEGORY_LARGE_AMOUNT,
        description="单笔交易金额达到大额交易申报阈值",
        field=FIELD_AMOUNT,
        operator=GTE,
        threshold={"value": "50000"},
        alert_level="轻度",
        weight="1.00",
    ),
    _rule(
        rule_code="R002",
        rule_name="单笔特大额交易",
        category=CATEGORY_LARGE_AMOUNT,
        description="单笔交易金额达到特大额标准，需立即关注",
        field=FIELD_AMOUNT,
        operator=GTE,
        threshold={"value": "1000000"},
        alert_level="重度",
        weight="3.00",
    ),
    _rule(
        rule_code="R003",
        rule_name="同日累计大额交易",
        category=CATEGORY_LARGE_AMOUNT,
        description="同一自然日内多笔交易金额合计达到大额标准",
        field=FIELD_AMOUNT,
        operator=DAILY_SUM_GTE,
        threshold={"value": "200000"},
        alert_level="中度",
        weight="2.00",
    ),
    _rule(
        rule_code="R004",
        rule_name="七日内累计大额交易",
        category=CATEGORY_LARGE_AMOUNT,
        description="连续七日内交易金额合计异常放大",
        field=FIELD_AMOUNT,
        operator=WINDOW_SUM_GTE,
        threshold={"value": "500000"},
        window_hours=WEEK,
        alert_level="中度",
        weight="2.00",
    ),
    _rule(
        rule_code="R005",
        rule_name="整数倍大额交易",
        category=CATEGORY_LARGE_AMOUNT,
        description="金额为万元整数倍的大额交易，金额疑似人为构造",
        field=FIELD_LARGE_ROUND_AMOUNT,
        operator=GTE,
        threshold={"value": "500000"},
        alert_level="轻度",
        weight="1.00",
    ),
    # ---------------- 频繁交易 ----------------
    _rule(
        rule_code="R006",
        rule_name="七日内频繁交易",
        category=CATEGORY_FREQUENT,
        description="连续七日内交易笔数达到频繁交易标准",
        field=FIELD_AMOUNT,
        operator=WINDOW_COUNT_GTE,
        threshold={"value": "10"},
        window_hours=WEEK,
        alert_level="中度",
        weight="1.50",
    ),
    _rule(
        rule_code="R007",
        rule_name="一小时内密集交易",
        category=CATEGORY_FREQUENT,
        description="极短时间内连续多笔交易，非正常投资节奏",
        field=FIELD_AMOUNT,
        operator=WINDOW_COUNT_GTE,
        threshold={"value": "5"},
        window_hours=HOUR,
        alert_level="中度",
        weight="1.50",
    ),
    _rule(
        rule_code="R008",
        rule_name="同日多笔交易",
        category=CATEGORY_FREQUENT,
        description="同一自然日内交易笔数偏多",
        field=FIELD_AMOUNT,
        operator=DAILY_COUNT_GTE,
        threshold={"value": "5"},
        alert_level="轻度",
        weight="1.00",
    ),
    _rule(
        rule_code="R009",
        rule_name="七日内频繁小额交易",
        category=CATEGORY_FREQUENT,
        description="连续七日内小额交易笔数异常，疑似化整为零",
        field=FIELD_SMALL_AMOUNT,
        operator=WINDOW_COUNT_GTE,
        threshold={"value": "20"},
        window_hours=WEEK,
        alert_level="中度",
        weight="1.50",
    ),
    _rule(
        rule_code="R010",
        rule_name="三十日内高频交易",
        category=CATEGORY_FREQUENT,
        description="一个月内交易笔数远超正常投资频率",
        field=FIELD_AMOUNT,
        operator=WINDOW_COUNT_GTE,
        threshold={"value": "30"},
        window_hours=MONTH,
        alert_level="中度",
        weight="2.00",
    ),
    # ---------------- 快进快出 ----------------
    _rule(
        rule_code="R011",
        rule_name="同产品二十四小时内快进快出",
        category=CATEGORY_QUICK_IN_OUT,
        description="同一产品在二十四小时内发生方向相反的交易",
        field=FIELD_REVERSE_INTERVAL_HOURS,
        operator=LTE,
        threshold={"value": "24"},
        alert_level="中度",
        weight="2.00",
    ),
    _rule(
        rule_code="R012",
        rule_name="同产品两小时内快进快出",
        category=CATEGORY_QUICK_IN_OUT,
        description="同一产品在两小时内发生方向相反的交易，资金过账特征明显",
        field=FIELD_REVERSE_INTERVAL_HOURS,
        operator=LTE,
        threshold={"value": "2"},
        alert_level="重度",
        weight="3.00",
    ),
    _rule(
        rule_code="R013",
        rule_name="二十四小时内多次申购",
        category=CATEGORY_QUICK_IN_OUT,
        description="短时间内反复申购，资金分批进入",
        field=FIELD_PURCHASE_AMOUNT,
        operator=WINDOW_COUNT_GTE,
        threshold={"value": "3"},
        window_hours=DAY,
        alert_level="轻度",
        weight="1.00",
    ),
    _rule(
        rule_code="R014",
        rule_name="二十四小时内多次赎回",
        category=CATEGORY_QUICK_IN_OUT,
        description="短时间内反复赎回，资金分批转出",
        field=FIELD_REDEEM_AMOUNT,
        operator=WINDOW_COUNT_GTE,
        threshold={"value": "3"},
        window_hours=DAY,
        alert_level="轻度",
        weight="1.00",
    ),
    # ---------------- 拆分规避 ----------------
    _rule(
        rule_code="R015",
        rule_name="疑似拆分规避申报阈值",
        category=CATEGORY_SPLITTING,
        description="多笔金额贴着大额申报阈值之下，合计却远超阈值",
        field=FIELD_THRESHOLD_AVOIDANCE_AMOUNT,
        operator=WINDOW_COUNT_GTE,
        threshold={"value": "3"},
        window_hours=DAY,
        alert_level="重度",
        weight="2.50",
    ),
    _rule(
        rule_code="R016",
        rule_name="二十四小时内分散至多个产品",
        category=CATEGORY_SPLITTING,
        description="短时间内资金分散到多个产品，规避单一产品的监测口径",
        field=FIELD_PRODUCT_ID,
        operator=WINDOW_DISTINCT_COUNT_GTE,
        threshold={"value": "5"},
        window_hours=DAY,
        alert_level="轻度",
        weight="1.00",
    ),
    # ---------------- 异常时段 ----------------
    _rule(
        rule_code="R017",
        rule_name="非工作时间交易",
        category=CATEGORY_ODD_HOURS,
        description="交易发生在营业时间之外，缺少人工复核",
        field=FIELD_HOUR_OF_DAY,
        operator=OUTSIDE,
        threshold={"min": "8", "max": "20"},
        alert_level="轻度",
        weight="1.00",
    ),
    # ---------------- 资产错配 ----------------
    _rule(
        rule_code="R018",
        rule_name="单笔金额占客户总资产比例异常",
        category=CATEGORY_MISMATCH,
        description="单笔金额与客户资产规模严重不符",
        field=FIELD_AMOUNT_TO_ASSETS_RATIO,
        operator=GTE,
        threshold={"value": "80"},
        alert_level="中度",
        weight="2.00",
    ),
    # ---------------- 适当性 ----------------
    _rule(
        rule_code="R019",
        rule_name="越级交易",
        category=CATEGORY_SUITABILITY,
        description="产品风险等级高于客户风险承受等级",
        field=FIELD_RISK_LEVEL_GAP,
        operator=GTE,
        threshold={"value": "1"},
        alert_level="重度",
        weight="2.50",
    ),
    # ---------------- 大额赎回 ----------------
    _rule(
        rule_code="R020",
        rule_name="大额赎回",
        category=CATEGORY_LARGE_AMOUNT,
        description="单笔赎回金额达到大额标准，资金大额离场",
        field=FIELD_REDEEM_AMOUNT,
        operator=GTE,
        threshold={"value": "500000"},
        alert_level="中度",
        weight="2.00",
    ),
)


def rule_seeds_by_code() -> dict[str, RuleSpec]:
    return {spec.rule_code: spec for spec in RISK_RULE_SEEDS}
