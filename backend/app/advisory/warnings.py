"""画像置信度低或已过期时的警示。

这里的「已过期」指画像本身太久没有重新计算（``computed_at`` 陈旧），
不是风险评测过期——评测过期已经在候选池检索层熔断（见
app.suitability），走不到这里。这里的警示只是提醒顾问「基于的信息
可能不新鲜」，不阻止生成。
"""

from datetime import datetime

CODE_LOW_CONFIDENCE = "LOW_CONFIDENCE"
CODE_PROFILE_STALE = "PROFILE_STALE"

MESSAGE_LOW_CONFIDENCE = "客户画像部分标签置信度偏低，生成结果可能基于不准确的信息，请核实后再采用"
MESSAGE_PROFILE_STALE = "客户画像距上次计算已超过 180 天，建议先刷新画像再生成方案"

# 与内部画像面板（ProfilePanel.vue 的 LOW_CONFIDENCE）保持一致的阈值。
LOW_CONFIDENCE_THRESHOLD = 0.5
PROFILE_STALE_DAYS = 180


def profile_warnings(*, tags: list[dict], computed_at: datetime, now: datetime) -> list[dict]:
    warnings: list[dict] = []
    if any(tag["confidence"] < LOW_CONFIDENCE_THRESHOLD for tag in tags):
        warnings.append({"code": CODE_LOW_CONFIDENCE, "message": MESSAGE_LOW_CONFIDENCE})
    if (now - computed_at).days >= PROFILE_STALE_DAYS:
        warnings.append({"code": CODE_PROFILE_STALE, "message": MESSAGE_PROFILE_STALE})
    return warnings
