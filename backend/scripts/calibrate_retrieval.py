"""golden 集校准两条检索兜底阈值（ADR-0022 决定 6）。

**为什么需要它。** `retrieval_score_threshold` 与 `retrieval_keyword_score_threshold`
是兜底判定（「该不该作答」）的输入（CONTEXT「证据分」），而这两个量都是**数据相关**的：

- 余弦那一侧取决于 embedding 模型——真实模型对无关文本的余弦也能到 0.4~0.5，
  阈值必须落在那条噪声基线之上；
- BM25 那一侧的 df / avgdl 在**全语料**上统计，语料规模一变，同一个问题的证据分就变。

所以两条阈值不能长期躺在注释里当经验值。本脚本在真实语料上跑一遍 golden 集
（`backend/tests/fixtures/retrieval_golden.json`），打印正例 / 负例的分臂证据分分布、
语料规模与建议阈值，供人工复核后写回 `app/settings.py` 与 `backend/.env.example`。

**为什么 CI 断言的是相对关系而不是这些绝对值。** 默认测试用 fake embedding（没有 key），
它给出的余弦与真实模型无关；BM25 虽然离线可跑，但绝对数值仍受语料规模影响。因此回归
测试（`backend/tests/test_retrieval_calibration.py`）只钉「正例得分高于负例、负例不达标」
这类相对关系，绝对数值由本脚本在真实 embedding 下产出——这是「真实 embedding 需要 key」
这个约束下唯一诚实的分工。**BM25 一侧本脚本完全离线可跑**（`jieba` 与 `rank_bm25`
都是纯本地库），只有余弦那一侧需要 key。

⚠️ **语料显著变化后要重跑本脚本。** BM25 证据分随语料规模漂移，因此输出里始终带着语料
规模（active 文档数与分块数）；脱离语料规模谈 `retrieval_keyword_score_threshold` 没有
意义。这是选 Python 侧 `rank_bm25`（Q7 c）相对 MySQL FULLTEXT 多出来的一份维护成本。

用法::

    cd backend
    python -m scripts.calibrate_retrieval                      # 用 backend/.env 的配置
    python -m scripts.calibrate_retrieval --database-url mysql+pymysql://...
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app import degradation
from app.db.models import DegradationTrace, KnowledgeChunk, KnowledgeMeta
from app.knowledge.service import STATUS_ACTIVE, search_chunks
from app.settings import Settings, get_settings

BACKEND_DIR = Path(__file__).resolve().parents[1]
DEFAULT_GOLDEN_PATH = BACKEND_DIR / "tests" / "fixtures" / "retrieval_golden.json"

# golden 集里正例的类 → 它由哪条召回臂服务。这不是「只有这条臂能找到它」，而是
# 「这一类正例存在的理由就是验证这条臂」：字面型与 FAQ 按对靠 BM25 的逐字命中，
# 语义型靠向量臂的相似度。建议阈值因此按臂分别从它对应的正例集里取。
ARM_KINDS: dict[str, tuple[str, ...]] = {
    "vector": ("semantic",),
    "keyword": ("literal", "faq"),
}

NEGATIVE_KIND = "negative"

# 分臂判定里两条阈值对应的设置项名（写回时用同一套名字）。
THRESHOLD_SETTING: dict[str, str] = {
    "vector": "retrieval_score_threshold",
    "keyword": "retrieval_keyword_score_threshold",
}

# 向量臂的建议值在两种情况下不可写回：余弦不是真实模型给的，或这一臂根本没跑起来。
FAKE_EMBEDDING_CAUTION = (
    "当前是 fake embedding，余弦与真实模型无关，建议不可写回；换真实 key 重跑。"
)
DEGRADED_VECTOR_CAUTION = (
    "本次运行期间向量臂走了降级路径（见 biz_degradation_trace），"
    "余弦恒记 0——量到的是「向量库坏了」而不是「余弦分布如何」；"
    "先修好向量库再重跑。"
)


@dataclass
class GoldenRun:
    """一条 golden 问题在两条召回臂上的实测证据分。

    字段名刻意叫 `evidence` 而不是 `scores`：装的是各臂的**证据分**（余弦 / BM25），
    与 `ChunkResult.score`（排序分）不是一回事（CONTEXT「证据分」的 _Avoid_ 明确
    包含「分数 / score」）。
    """

    question: str
    kind: str  # 正例取 golden 里的 kind，负例固定为 NEGATIVE_KIND
    evidence: dict[str, float]
    # 正例：期望的分块（source_file + snippet）是否进了候选池；负例恒为 None。
    hit: bool | None


@dataclass
class ThresholdSuggestion:
    arm: str
    value: float | None
    separable: bool
    detail: str
    positive_evidence: list[float]
    negative_evidence: list[float]
    # 非空表示这条建议不该被直接写回（fake embedding / 向量臂本次降级）。
    caution: str = ""


def load_golden(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def corpus_size(db: Session) -> tuple[int, int]:
    """(active 文档数, active 分块数)。BM25 的 df / avgdl 只统计 active 分块。"""
    documents = db.scalar(
        select(func.count())
        .select_from(KnowledgeMeta)
        .where(KnowledgeMeta.status == STATUS_ACTIVE)
    )
    chunks = db.scalar(
        select(func.count())
        .select_from(KnowledgeChunk)
        .join(KnowledgeMeta, KnowledgeMeta.id == KnowledgeChunk.knowledge_id)
        .where(KnowledgeMeta.status == STATUS_ACTIVE)
    )
    return int(documents or 0), int(chunks or 0)


def collect_runs(
    db: Session, settings: Settings, golden: dict, *, top_k: int
) -> list[GoldenRun]:
    """跑一遍 golden 集，读**分臂证据分**（`RetrievedChunks.evidence`）。

    校准的目标量是各召回臂的原始最高分（余弦 / BM25），不是 `ChunkResult.score`——
    后者是 RRF 或重排写出的排序分，跨查询不可比，读错字段会得出一个看着像结论的
    错数字（spec「校准的目标量是 evidence_score，不是 score」）。
    """
    runs: list[GoldenRun] = []
    for item in golden["positives"]:
        runs.append(_run_one(db, settings, item, kind=item["kind"], top_k=top_k))
    for item in golden["negatives"]:
        runs.append(_run_one(db, settings, item, kind=NEGATIVE_KIND, top_k=top_k))
    return runs


def _run_one(
    db: Session, settings: Settings, item: dict, *, kind: str, top_k: int
) -> GoldenRun:
    candidates = search_chunks(db, settings, query=item["question"], top_k=top_k)
    evidence = {arm: float(candidates.evidence.get(arm, 0.0)) for arm in ARM_KINDS}
    hit: bool | None = None
    if kind != NEGATIVE_KIND:
        snippet = item.get("snippet", "")
        source_file = item.get("source_file", "")
        hit = any(
            chunk.source_file == source_file and snippet and snippet in chunk.content
            for chunk in candidates
        )
    return GoldenRun(question=item["question"], kind=kind, evidence=evidence, hit=hit)


def suggest_thresholds(runs: Sequence[GoldenRun]) -> list[ThresholdSuggestion]:
    negatives = [run for run in runs if run.kind == NEGATIVE_KIND]
    suggestions: list[ThresholdSuggestion] = []
    for arm, kinds in ARM_KINDS.items():
        positives = [run for run in runs if run.kind in kinds]
        suggestions.append(
            _suggest(
                arm,
                positive_evidence=[run.evidence[arm] for run in positives],
                negative_evidence=[run.evidence[arm] for run in negatives],
            )
        )
    return suggestions


def _suggest(
    arm: str, *, positive_evidence: list[float], negative_evidence: list[float]
) -> ThresholdSuggestion:
    """建议阈值 = 最差负例与最低正例的中点；两者重叠时给出最大间隔中点并标注。

    这是「用数据集量出来的值」而不是拍一个数：阈值只要落在负例之上、正例之下即可，
    中点是对两侧余量的对半分配。分布重叠说明 golden 集或语料该修（补负例、换措辞），
    这种情况不能靠调阈值掩盖过去，因此标成不可信、由人工复核。
    """
    if not positive_evidence or not negative_evidence:
        return ThresholdSuggestion(
            arm=arm,
            value=None,
            separable=False,
            detail="正例或负例为空，无法给出建议",
            positive_evidence=positive_evidence,
            negative_evidence=negative_evidence,
        )

    worst_negative = max(negative_evidence)
    hardest_positive = min(positive_evidence)
    separable = hardest_positive > worst_negative
    if separable:
        value = (worst_negative + hardest_positive) / 2
        detail = (
            f"取最差负例 {worst_negative:.4g} 与最低正例 {hardest_positive:.4g} 的中点"
        )
    else:
        ordered = sorted([*negative_evidence, *positive_evidence])
        gaps = [ordered[index + 1] - ordered[index] for index in range(len(ordered) - 1)]
        cut = gaps.index(max(gaps))
        value = (ordered[cut] + ordered[cut + 1]) / 2
        detail = (
            f"正负例分布重叠（最差负例 {worst_negative:.4g} ≥ 最低正例 "
            f"{hardest_positive:.4g}），给出最大间隔中点，需人工复核"
        )
    return ThresholdSuggestion(
        arm=arm,
        value=round(value, 4),
        separable=separable,
        detail=detail,
        positive_evidence=positive_evidence,
        negative_evidence=negative_evidence,
    )


def vector_arm_is_real(settings: Settings) -> bool:
    """余弦那一侧是否需要 key：fake embedding 下的余弦与真实模型无关，不可据以校准。"""
    return settings.resolved_embedding_provider != "fake"


def _last_degradation_id(db: Session) -> int:
    return int(db.scalar(select(func.max(DegradationTrace.id))) or 0)


def vector_arm_degraded(db: Session, *, since_id: int) -> bool:
    """本次运行期间向量臂是否走了降级路径。

    `RetrievedChunks.evidence` 分不清「向量臂没块达标」与「向量臂整个降级」——降级时
    `evidence["vector"]` 恒为 0，于是脚本会照常打印一个 0 附近的向量建议值，看着像结论
    其实是「向量库坏了」。因此跑之前记下留痕的最大 id，跑完查这一段里有没有
    `vector_store` 依赖的记录。
    """
    return (
        db.scalar(
            select(DegradationTrace.id)
            .where(
                DegradationTrace.id > since_id,
                DegradationTrace.dependency == degradation.DEPENDENCY_VECTOR,
            )
            .limit(1)
        )
        is not None
    )


def render_text(
    settings: Settings,
    *,
    documents: int,
    chunks: int,
    runs: Sequence[GoldenRun],
    suggestions: Sequence[ThresholdSuggestion],
    top_k: int,
) -> str:
    lines: list[str] = []
    lines.append("=== 校准语料（BM25 证据分随语料规模漂移，务必连它一起记录）===")
    lines.append(f"数据库: {settings.database_url}")
    lines.append(f"active 文档: {documents}    active 分块: {chunks}")
    lines.append(
        f"向量臂: {settings.resolved_embedding_provider} / {settings.embedding_model_name}"
        + ("" if vector_arm_is_real(settings) else "（fake：余弦不可据以校准）")
    )
    lines.append("关键词臂: BM25（rank_bm25 + jieba，df/avgdl 在全语料上统计）")
    lines.append(f"召回条数 top_k: {top_k}")
    lines.append("")

    positives = [run for run in runs if run.kind != NEGATIVE_KIND]
    negatives = [run for run in runs if run.kind == NEGATIVE_KIND]
    hits = sum(1 for run in positives if run.hit)
    lines.append(f"=== 正例（{len(positives)} 条，期望分块进入候选 {hits} 条）===")
    lines.append(f"{'kind':<9}{'向量余弦':>10}{'关键词BM25':>12}  命中  问题")
    for run in positives:
        # 只用 GBK 可编码的字符：Windows 控制台默认是 GBK，非 GBK 符号会直接把
        # 输出整个打崩（UnicodeEncodeError），校准结果反而看不到。
        mark = "hit " if run.hit else "MISS"
        lines.append(
            f"{run.kind:<9}{run.evidence['vector']:>10.4f}{run.evidence['keyword']:>12.4f}"
            f"  {mark}    {run.question}"
        )
    lines.append("")

    lines.append(f"=== 负例（{len(negatives)} 条，期望什么都不命中）===")
    lines.append(f"{'向量余弦':>10}{'关键词BM25':>12}  问题")
    for run in negatives:
        lines.append(
            f"{run.evidence['vector']:>10.4f}{run.evidence['keyword']:>12.4f}  {run.question}"
        )
    lines.append("")

    lines.append("=== 分布与建议阈值 ===")
    for suggestion in suggestions:
        setting = THRESHOLD_SETTING[suggestion.arm]
        lines.append(f"[{suggestion.arm} 臂] {setting}")
        if suggestion.positive_evidence:
            lines.append(
                f"  正例({len(suggestion.positive_evidence)}): "
                f"min {min(suggestion.positive_evidence):.4g} "
                f"max {max(suggestion.positive_evidence):.4g}"
            )
        if suggestion.negative_evidence:
            lines.append(
                f"  负例({len(suggestion.negative_evidence)}): "
                f"min {min(suggestion.negative_evidence):.4g} "
                f"max {max(suggestion.negative_evidence):.4g}"
            )
        if suggestion.value is None:
            lines.append(f"  建议: 无法给出（{suggestion.detail}）")
        else:
            note = "" if suggestion.separable else "  [WARN] 不可信"
            lines.append(f"  建议 {setting} = {suggestion.value}{note}（{suggestion.detail}）")
        if suggestion.caution:
            lines.append(f"  [WARN] {suggestion.caution}")
        lines.append("")

    lines.append(
        "[WARN] 语料显著变化后要重跑本脚本（BM25 证据分随语料规模漂移）；建议值人工复核后"
        "写回 app/settings.py 与 backend/.env.example。"
    )
    return "\n".join(lines)


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default="",
        help="覆盖 settings.database_url（默认用 backend/.env 的配置）",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    settings = get_settings()
    if args.database_url:
        settings = settings.model_copy(update={"database_url": args.database_url})
    top_k = settings.hybrid_recall_top_k

    golden = load_golden(DEFAULT_GOLDEN_PATH)
    engine = create_engine(settings.database_url)
    try:
        with Session(engine) as db:
            documents, chunks = corpus_size(db)
            before = _last_degradation_id(db)
            runs = collect_runs(db, settings, golden, top_k=top_k)
            vector_degraded = vector_arm_degraded(db, since_id=before)
    finally:
        engine.dispose()

    suggestions = suggest_thresholds(runs)
    for suggestion in suggestions:
        if suggestion.arm != "vector":
            continue
        if not vector_arm_is_real(settings):
            suggestion.caution = FAKE_EMBEDDING_CAUTION
        elif vector_degraded:
            suggestion.caution = DEGRADED_VECTOR_CAUTION

    print(
        render_text(
            settings,
            documents=documents,
            chunks=chunks,
            runs=runs,
            suggestions=suggestions,
            top_k=top_k,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
