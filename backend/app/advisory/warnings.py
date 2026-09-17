"""画像置信度低、已过期，或风控刚发出预警时的警示。

这里的「已过期」指画像本身太久没有重新计算（``computed_at`` 陈旧），
不是风险评测过期——评测过期已经在候选池检索层熔断（见
app.suitability），走不到这里。这里的警示只是提醒顾问「基于的信息
可能不新鲜」，不阻止生成。

风险标记同理：它是**提示**，不是拦截。风控预警说明这位客户此刻值得看一眼，
但方案生成与否、给什么方案仍由持证顾问判断（CONTEXT「审核」）。
"""

from datetime import datetime

CODE_LOW_CONFIDENCE = "LOW_CONFIDENCE"
CODE_PROFILE_STALE = "PROFILE_STALE"
CODE_ACTIVE_RISK_ALERT = "ACTIVE_RISK_ALERT"

MESSAGE_LOW_CONFIDENCE = "客户画像部分标签置信度偏低，生成结果可能基于不准确的信息，请核实后再采用"
MESSAGE_PROFILE_STALE = "客户画像距上次计算已超过 180 天，建议先刷新画像再生成方案"

# 与内部画像面板（ProfilePanel.vue 的 LOW_CONFIDENCE）保持一致的阈值。
LOW_CONFIDENCE_THRESHOLD = 0.5
PROFILE_STALE_DAYS = 180

# 风险标记的回溯窗口：更早的预警不再出现在方案上——顾问要为「现在」把关，一条
# 半年前的预警混进今天的配置建议里只会变成噪音。
RISK_FOCUS_LOOKBACK_DAYS = 30
# 一条提示里最多列出几条预警明细，其余只计数：方案上的一句警示不该长成一张表格。
RISK_FOCUS_DETAIL_LIMIT = 3


def profile_warnings(*, tags: list[dict], computed_at: datetime, now: datetime) -> list[dict]:
    warnings: list[dict] = []
    if any(tag["confidence"] < LOW_CONFIDENCE_THRESHOLD for tag in tags):
        warnings.append({"code": CODE_LOW_CONFIDENCE, "message": MESSAGE_LOW_CONFIDENCE})
    if (now - computed_at).days >= PROFILE_STALE_DAYS:
        warnings.append({"code": CODE_PROFILE_STALE, "message": MESSAGE_PROFILE_STALE})
    return warnings


def risk_focus_warnings(focuses: list[dict]) -> list[dict]:
    """风控预警在方案上的标记。

    订阅方为每条预警各写一条关注记录，方案上只汇总成一条：顾问要的是「这位客户
    现在有风险」与它的来处，而不是一串几乎相同的预警。时间基准由调用方传入窗口
    （ADR-0011），这里只做呈现。
    """
    if not focuses:
        return []
    details = "、".join(
        f"{focus['severity'] or '未分级'}（{focus['occurred_at']:%Y-%m-%d}）"
        for focus in focuses[:RISK_FOCUS_DETAIL_LIMIT]
    )
    more = f"等 {len(focuses)} 条" if len(focuses) > RISK_FOCUS_DETAIL_LIMIT else ""
    return [
        {
            "code": CODE_ACTIVE_RISK_ALERT,
            "message": (
                f"该客户近 {RISK_FOCUS_LOOKBACK_DAYS} 天内有风控预警：{details}{more}，"
                "生成方案前请先确认处置情况"
            ),
        }
    ]
