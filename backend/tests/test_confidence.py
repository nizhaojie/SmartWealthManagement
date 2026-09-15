from datetime import datetime, timedelta

from app.customer_profile.confidence import compute_confidence


def test_questionnaire_source_starts_at_point_nine():
    observed_at = datetime(2026, 1, 1, 12, 0, 0)
    assert (
        compute_confidence(
            source="风评问卷",
            evidence_count=0,
            conflict_count=0,
            observed_at=observed_at,
            now=observed_at,
        )
        == 0.9
    )


def test_evidence_gain_is_capped():
    observed_at = datetime(2026, 1, 1, 12, 0, 0)
    assert (
        compute_confidence(
            source="AI对话提取",
            evidence_count=5,
            conflict_count=0,
            observed_at=observed_at,
            now=observed_at,
        )
        == 0.85
    )


def test_conflict_applies_a_penalty():
    observed_at = datetime(2026, 1, 1, 12, 0, 0)
    assert (
        compute_confidence(
            source="客户自述",
            evidence_count=0,
            conflict_count=1,
            observed_at=observed_at,
            now=observed_at,
        )
        == 0.45
    )


def test_one_year_decays_by_point_two_using_passed_now():
    observed_at = datetime(2025, 1, 1, 12, 0, 0)
    now = observed_at + timedelta(days=365)
    assert (
        compute_confidence(
            source="风评问卷",
            evidence_count=0,
            conflict_count=0,
            observed_at=observed_at,
            now=now,
        )
        == 0.7
    )


def test_confidence_is_clamped_to_zero_and_one():
    observed_at = datetime(2024, 1, 1, 12, 0, 0)
    now = observed_at + timedelta(days=730)
    assert (
        compute_confidence(
            source="默认值",
            evidence_count=0,
            conflict_count=4,
            observed_at=observed_at,
            now=now,
        )
        == 0.0
    )
    assert (
        compute_confidence(
            source="理财顾问手工修正",
            evidence_count=3,
            conflict_count=0,
            observed_at=observed_at,
            now=observed_at,
        )
        == 1.0
    )
