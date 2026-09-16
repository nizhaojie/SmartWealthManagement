"""预警分级与置信度：确定性代码的纯函数测试。

分级只看命中的条数与该客户有没有历史预警，置信度只由命中规则的权重折算。两者都
不依赖数据库、不读时钟、也不经过模型，所以可以直接喂 RuleHit 断言输出。

这里固定两条容易被人「优化」掉的性质：
- 权重再大、置信度再高，单条命中也只是轻度（分级不看分数）；
- 置信度不参与任何关闭判断（低置信不会让预警消失）。

末尾一并覆盖求值要回溯多久历史：那是分级的前一步，同样是没有外部依赖的纯计算。
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from app.risk_monitoring.alerting import history_lookback_hours
from app.risk_monitoring.context import RuleHit
from app.risk_monitoring.grading import (
    CONFIDENCE_FULL_SCORE,
    LEVEL_LIGHT,
    LEVEL_MODERATE,
    LEVEL_SEVERE,
    alert_type_for,
    compute_confidence,
    grade_alert_level,
    render_trigger_detail,
)
from app.risk_monitoring.rules import RISK_RULE_SEEDS


def _hit(
    rule_code: str = "R001",
    *,
    rule_name: str = "单笔大额交易",
    category: str = "大额交易",
    weight: str = "1.00",
    evidence: str = "交易金额 600000 ≥ 阈值 50000",
) -> RuleHit:
    return RuleHit(
        rule_code=rule_code,
        rule_name=rule_name,
        category=category,
        alert_level=LEVEL_LIGHT,
        weight=Decimal(weight),
        field="amount",
        field_label="交易金额",
        operator="gte",
        threshold="50000",
        observed_value="600000",
        evidence=evidence,
    )


def test_a_single_hit_is_light_regardless_of_how_heavy_the_rule_is():
    """单条命中就是轻度，哪怕它是权重最高的规则、客户还有历史预警。

    分级看的是「几条规则交叉」，不是「这条规则多重」——否则把一条规则的阈值调低
    就能把一个客户顶成重度。
    """
    assert grade_alert_level(1, has_prior_alert=False) == LEVEL_LIGHT
    assert grade_alert_level(1, has_prior_alert=True) == LEVEL_LIGHT


def test_crossing_rules_without_a_history_is_moderate():
    assert grade_alert_level(2, has_prior_alert=False) == LEVEL_MODERATE
    assert grade_alert_level(6, has_prior_alert=False) == LEVEL_MODERATE


def test_crossing_rules_with_a_history_is_severe():
    assert grade_alert_level(2, has_prior_alert=True) == LEVEL_SEVERE
    assert grade_alert_level(6, has_prior_alert=True) == LEVEL_SEVERE


def test_confidence_sums_the_weights_of_the_hits():
    single = compute_confidence([_hit(weight="1.00")])
    assert single == Decimal("0.10")
    assert single == Decimal("1.00") / CONFIDENCE_FULL_SCORE

    heavier = compute_confidence([_hit(weight="1.00"), _hit("R002", weight="3.00")])
    assert heavier == Decimal("0.40")


def test_confidence_rounds_half_up_to_two_decimals():
    # 2.50 / 10.00 = 0.25，1.00 + 2.50 = 3.50 -> 0.35；0.125 这类值四舍五入而不是截断。
    assert compute_confidence([_hit(weight="2.50"), _hit(weight="1.00")]) == Decimal("0.35")
    assert compute_confidence([_hit(weight="1.25")]) == Decimal("0.13")


def test_confidence_is_capped_at_one():
    hits = [_hit(f"R{i:03d}", weight="3.00") for i in range(1, 9)]
    assert compute_confidence(hits) == Decimal("1.00")


def test_confidence_never_changes_the_level():
    """分数只用于排序与展示，不参与分级：低分与高分走同一条分级代码。"""
    low = [_hit(weight="0.50"), _hit("R008", weight="0.50")]
    high = [_hit(weight="3.00"), _hit("R012", weight="3.00")]

    assert compute_confidence(low) < compute_confidence(high)
    assert grade_alert_level(len(low), has_prior_alert=False) == grade_alert_level(
        len(high), has_prior_alert=False
    )


def test_alert_type_is_the_heaviest_total_not_the_first_hit():
    hits = [
        _hit("R001", category="大额交易", weight="1.00"),
        _hit("R007", category="频繁交易", weight="1.50"),
        _hit("R008", category="频繁交易", weight="1.00"),
    ]
    assert alert_type_for(hits) == "频繁交易"


def test_alert_type_breaks_ties_towards_the_earlier_rule():
    hits = [
        _hit("R001", category="大额交易", weight="1.00"),
        _hit("R008", category="频繁交易", weight="1.00"),
    ]
    assert alert_type_for(hits) == "大额交易"


def test_trigger_detail_keeps_field_value_and_threshold_on_every_line():
    detail = render_trigger_detail(
        [
            _hit("R001", rule_name="单笔大额交易", evidence="交易金额 600000 ≥ 阈值 50000"),
            _hit("R007", rule_name="一小时内密集交易", evidence="1 小时内的笔数 6 ≥ 阈值 5"),
        ]
    )

    lines = detail.splitlines()
    assert len(lines) == 2
    assert "单笔大额交易（R001）" in lines[0]
    assert "交易金额 600000 ≥ 阈值 50000" in lines[0]
    assert "1 小时内的笔数 6 ≥ 阈值 5" in lines[1]


def test_history_lookback_covers_every_window_the_rules_use():
    """历史窗口必须覆盖最长的时间窗，否则窗口内的笔数会凭空变少——漏报而不报错。"""
    longest_window = max(rule.window_hours or 0 for rule in RISK_RULE_SEEDS)
    assert history_lookback_hours(list(RISK_RULE_SEEDS)) == longest_window


def test_history_lookback_never_falls_below_a_day():
    """同日累计类算子也读历史，它们没有 window_hours。

    只按时间窗取最长值会让回溯变成 0，那时「同日累计」只看得到本笔一笔。
    """
    no_window = replace(RISK_RULE_SEEDS[0], window_hours=None)
    assert history_lookback_hours([no_window]) == 24
    assert history_lookback_hours([]) == 24
