from datetime import datetime

SOURCE_ADVISOR = "理财顾问手工修正"
SOURCE_QUESTIONNAIRE = "风评问卷"
SOURCE_AI_EXTRACT = "AI对话提取"
SOURCE_SELF_REPORTED = "客户自述"
SOURCE_DEFAULT = "默认值"

SOURCE_INITIAL_CONFIDENCE = {
    SOURCE_ADVISOR: 0.95,
    SOURCE_QUESTIONNAIRE: 0.90,
    SOURCE_AI_EXTRACT: 0.70,
    SOURCE_SELF_REPORTED: 0.55,
    SOURCE_DEFAULT: 0.30,
}

EVIDENCE_GAIN_STEP = 0.05
EVIDENCE_GAIN_CAP = 0.15
CONFLICT_PENALTY_STEP = 0.10
DECAY_PER_YEAR = 0.20
SECONDS_PER_YEAR = 365 * 24 * 3600

UNKNOWN_SOURCE_MESSAGE = "未知的标签来源"


def source_rank(source: str) -> float:
    if source not in SOURCE_INITIAL_CONFIDENCE:
        raise ValueError(UNKNOWN_SOURCE_MESSAGE)
    return SOURCE_INITIAL_CONFIDENCE[source]


def compute_confidence(
    *,
    source: str,
    evidence_count: int,
    conflict_count: int,
    observed_at: datetime,
    now: datetime,
) -> float:
    initial = source_rank(source)
    evidence_gain = min(evidence_count * EVIDENCE_GAIN_STEP, EVIDENCE_GAIN_CAP)
    conflict_penalty = conflict_count * CONFLICT_PENALTY_STEP
    elapsed = max((now - observed_at).total_seconds(), 0.0)
    decay = (elapsed / SECONDS_PER_YEAR) * DECAY_PER_YEAR
    raw = initial + evidence_gain - conflict_penalty - decay
    return round(max(0.0, min(1.0, raw)), 4)
