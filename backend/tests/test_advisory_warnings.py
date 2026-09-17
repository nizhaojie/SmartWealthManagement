"""画像置信度低或已过期（画像本身陈旧）时的警示（issue 01），
以及风控预警带来的风险标记（ticket 04）。"""

from datetime import datetime, timedelta

from app.advisory.warnings import (
    CODE_ACTIVE_RISK_ALERT,
    CODE_LOW_CONFIDENCE,
    CODE_PROFILE_STALE,
    RISK_FOCUS_DETAIL_LIMIT,
    profile_warnings,
    risk_focus_warnings,
)

NOW = datetime(2026, 1, 1, 12, 0, 0)
FRESH = NOW - timedelta(days=1)
STALE = NOW - timedelta(days=200)

CONFIDENT_TAGS = [{"key": "risk_level", "confidence": 0.9}]
LOW_CONFIDENCE_TAGS = [{"key": "risk_level", "confidence": 0.9}, {"key": "product_preference", "confidence": 0.3}]


def test_confident_and_fresh_profile_has_no_warnings():
    assert profile_warnings(tags=CONFIDENT_TAGS, computed_at=FRESH, now=NOW) == []


def test_a_tag_below_the_confidence_threshold_triggers_a_warning():
    codes = {w["code"] for w in profile_warnings(tags=LOW_CONFIDENCE_TAGS, computed_at=FRESH, now=NOW)}
    assert CODE_LOW_CONFIDENCE in codes


def test_a_profile_not_recomputed_in_over_180_days_triggers_a_warning():
    codes = {w["code"] for w in profile_warnings(tags=CONFIDENT_TAGS, computed_at=STALE, now=NOW)}
    assert CODE_PROFILE_STALE in codes


def test_both_warnings_can_fire_together():
    codes = {w["code"] for w in profile_warnings(tags=LOW_CONFIDENCE_TAGS, computed_at=STALE, now=NOW)}
    assert codes == {CODE_LOW_CONFIDENCE, CODE_PROFILE_STALE}


# --- 风控预警带来的风险标记（ticket 04） ---


def _focus(severity: str, days_ago: int) -> dict:
    return {"severity": severity, "occurred_at": NOW - timedelta(days=days_ago)}


def test_no_risk_focus_means_no_marker():
    assert risk_focus_warnings([]) == []


def test_a_risk_focus_marks_the_plan_with_its_level_and_date():
    warnings = risk_focus_warnings([_focus("重度", 1)])

    assert [w["code"] for w in warnings] == [CODE_ACTIVE_RISK_ALERT]
    assert "重度" in warnings[0]["message"]
    assert (NOW - timedelta(days=1)).strftime("%Y-%m-%d") in warnings[0]["message"]


def test_many_focuses_are_summarised_into_one_marker():
    """订阅方为每条预警各写一条记录，方案上只出现一条提示。"""
    focuses = [_focus("中度", days) for days in range(1, RISK_FOCUS_DETAIL_LIMIT + 4)]

    warnings = risk_focus_warnings(focuses)

    assert len(warnings) == 1
    assert f"等 {len(focuses)} 条" in warnings[0]["message"]


def test_a_focus_without_a_level_still_reads_as_a_marker():
    warnings = risk_focus_warnings([{"severity": None, "occurred_at": NOW}])

    assert "未分级" in warnings[0]["message"]
