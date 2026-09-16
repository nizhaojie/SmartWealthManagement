"""画像置信度低或已过期（画像本身陈旧）时的警示（issue 01）。"""

from datetime import datetime, timedelta

from app.advisory.warnings import CODE_LOW_CONFIDENCE, CODE_PROFILE_STALE, profile_warnings

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
