"""置信度的综合重排（五因子、按场景配置权重）。

画像标签的基础置信分在 `confidence.py` 里算出来；但同一批记忆单元在不同场景下应当有
不同的先后：做产品推荐时「与当前问题有多相关」最重要，做风险研判时「有多新」最重要，
复核画像时「历史上准不准」与基础分更重要。这一层单独做成纯函数。

五因子：

- **语义相似度** `semantic_similarity`：单元与当前查询/任务的相关程度，由调用方给出。
- **时效性** `recency`：由 ``observed_at`` 与显式传入的 ``now`` 相减得出（ADR-0011）。
- **历史准确率** `historical_accuracy`：该单元历史上被后续独立证据确认的程度，由调用方给出。
- **基础置信分** `base_confidence`：``compute_confidence`` 的结果。
- **冲突惩罚** `conflict_penalty`：被相反证据冲撞的次数归一化，作为加权减项。

权重按场景配置在 ``DEFAULT_SCENARIO_WEIGHTS`` 这张表里，公式中不出现任何数字；
``Settings.confidence_rerank_weights`` 可以给同一张表提供覆盖值，调整策略不改代码。

**输出是排序，不是过滤。** 所有传入的单元都会出现在结果里，低分的排在后面；要不要
丢弃、丢弃到什么程度，是调用方的事（不同调用方的下限不同，重排不该替它们决定）。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

FACTOR_SEMANTIC_SIMILARITY = "semantic_similarity"
FACTOR_RECENCY = "recency"
FACTOR_HISTORICAL_ACCURACY = "historical_accuracy"
FACTOR_BASE_CONFIDENCE = "base_confidence"
FACTOR_CONFLICT_PENALTY = "conflict_penalty"

FACTORS = (
    FACTOR_SEMANTIC_SIMILARITY,
    FACTOR_RECENCY,
    FACTOR_HISTORICAL_ACCURACY,
    FACTOR_BASE_CONFIDENCE,
    FACTOR_CONFLICT_PENALTY,
)

SCENARIO_CUSTOMER_SERVICE = "customer_service"
SCENARIO_PRODUCT_RECOMMENDATION = "product_recommendation"
SCENARIO_RISK_ANALYSIS = "risk_analysis"
SCENARIO_PROFILE_REVIEW = "profile_review"

SCENARIO_LABELS = {
    SCENARIO_CUSTOMER_SERVICE: "客服问答",
    SCENARIO_PRODUCT_RECOMMENDATION: "产品推荐",
    SCENARIO_RISK_ANALYSIS: "风险研判",
    SCENARIO_PROFILE_REVIEW: "画像复核",
}

# 场景权重表：每个场景五个因子的权重之和为 1，冲突惩罚是减项。
# 产品推荐把语义相似度放在最高位，风险研判把时效性放在最高位——同一批单元、不同的
# 权重，排出来的先后就不同，这正是「同一批记忆单元在不同场景下排序不同」的实现。
DEFAULT_SCENARIO_WEIGHTS: dict[str, dict[str, float]] = {
    SCENARIO_CUSTOMER_SERVICE: {
        FACTOR_SEMANTIC_SIMILARITY: 0.45,
        FACTOR_RECENCY: 0.20,
        FACTOR_HISTORICAL_ACCURACY: 0.10,
        FACTOR_BASE_CONFIDENCE: 0.20,
        FACTOR_CONFLICT_PENALTY: 0.05,
    },
    SCENARIO_PRODUCT_RECOMMENDATION: {
        FACTOR_SEMANTIC_SIMILARITY: 0.50,
        FACTOR_RECENCY: 0.10,
        FACTOR_HISTORICAL_ACCURACY: 0.10,
        FACTOR_BASE_CONFIDENCE: 0.20,
        FACTOR_CONFLICT_PENALTY: 0.10,
    },
    SCENARIO_RISK_ANALYSIS: {
        FACTOR_SEMANTIC_SIMILARITY: 0.15,
        FACTOR_RECENCY: 0.50,
        FACTOR_HISTORICAL_ACCURACY: 0.10,
        FACTOR_BASE_CONFIDENCE: 0.15,
        FACTOR_CONFLICT_PENALTY: 0.10,
    },
    SCENARIO_PROFILE_REVIEW: {
        FACTOR_SEMANTIC_SIMILARITY: 0.10,
        FACTOR_RECENCY: 0.20,
        FACTOR_HISTORICAL_ACCURACY: 0.30,
        FACTOR_BASE_CONFIDENCE: 0.30,
        FACTOR_CONFLICT_PENALTY: 0.10,
    },
}

# 时效性归零的跨度：超过这个天数，单元在「有多新」这一项上得 0 分。
RECENCY_HORIZON_DAYS = 365.0

SECONDS_PER_DAY = 24 * 3600

UNKNOWN_SCENARIO_MESSAGE = "未知的重排场景"
MISSING_FACTOR_MESSAGE = "场景权重缺少因子"


@dataclass(frozen=True)
class MemoryUnit:
    """一个待重排的记忆单元，五个因子都由调用方或适配器填好值。"""

    key: str
    semantic_similarity: float
    observed_at: datetime
    historical_accuracy: float
    base_confidence: float
    conflict_penalty: float


@dataclass(frozen=True)
class RankedUnit:
    """重排结果：总分与每个因子的加权贡献（冲突惩罚是负值）。"""

    key: str
    score: float
    factors: dict[str, float]


def weights_for_scenario(
    scenario: str,
    *,
    overrides: Mapping[str, Mapping[str, float]] | None = None,
) -> dict[str, float]:
    """取一个场景的权重；``overrides`` 给出同构表时用它替换对应场景的缺省值。

    未知场景抛 ``ValueError``——与 ``confidence.source_rank`` 同一口径，由 API 层
    翻译成业务错误码，纯计算模块不认识 HTTP。
    """
    if scenario not in DEFAULT_SCENARIO_WEIGHTS:
        raise ValueError(UNKNOWN_SCENARIO_MESSAGE)
    weights = dict(DEFAULT_SCENARIO_WEIGHTS[scenario])
    if overrides:
        weights.update(overrides.get(scenario, {}))
    return weights


def rerank(
    units: Sequence[MemoryUnit],
    *,
    weights: Mapping[str, float],
    now: datetime,
) -> list[RankedUnit]:
    """按五因子加权分给一批记忆单元排序。

    时间基准由参数传入（ADR-0011）：时效性由 ``observed_at`` 与 ``now`` 相减得出，
    于是「一句基准为一年前时它排在后面」是一个可以直接断言的纯计算。返回的列表与
    输入等长——被排到后面的单元仍然在列表里。
    """
    for factor in FACTORS:
        if factor not in weights:
            raise ValueError(MISSING_FACTOR_MESSAGE)

    ranked = [_rank_unit(unit, weights=weights, now=now) for unit in units]
    # 并列时按 key 排序：顺序稳定，同一次输入重跑两次结果一致。
    ranked.sort(key=lambda item: (-item.score, item.key))
    return ranked


def _rank_unit(unit: MemoryUnit, *, weights: Mapping[str, float], now: datetime) -> RankedUnit:
    values = {
        FACTOR_SEMANTIC_SIMILARITY: _clamp(unit.semantic_similarity),
        FACTOR_RECENCY: recency(unit.observed_at, now),
        FACTOR_HISTORICAL_ACCURACY: _clamp(unit.historical_accuracy),
        FACTOR_BASE_CONFIDENCE: _clamp(unit.base_confidence),
        FACTOR_CONFLICT_PENALTY: _clamp(unit.conflict_penalty),
    }
    factors = {
        factor: round(weights[factor] * value, 4) for factor, value in values.items()
    }
    factors[FACTOR_CONFLICT_PENALTY] = -factors[FACTOR_CONFLICT_PENALTY]
    return RankedUnit(key=unit.key, score=round(sum(factors.values()), 4), factors=factors)


def recency(observed_at: datetime, now: datetime) -> float:
    """时效性：越新越高，``RECENCY_HORIZON_DAYS`` 天以前归零。

    ``observed_at`` 晚于 ``now``（时钟回拨或数据异常）时按「刚刚」处理，取 1.0，
    不让一个未来的时间戳把分数推出 [0, 1]。
    """
    elapsed_days = max((now - observed_at).total_seconds() / SECONDS_PER_DAY, 0.0)
    return max(0.0, 1.0 - elapsed_days / RECENCY_HORIZON_DAYS)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))
