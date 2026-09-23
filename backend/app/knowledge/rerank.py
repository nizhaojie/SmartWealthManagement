"""候选集的 LLM 重排（增强，可降级；ADR-0022 决定 3 与 5）。

位置：混合召回（RRF）之后、图谱融合之前，只作用于相似度候选。它只决定「谁排在
前面」，不决定「该不该作答」——那是分臂证据（`route_after_retrieve`）的职责；也不给
图谱段落排序——那是查出来的确定事实。因此这里的每一条失败路径都退回 RRF 序并留下
一条 `rerank` 依赖的降级痕迹：重排失败绝不能变成整体检索失败（CONTEXT「降级」）。

模块摆放：本模块 import `app.llm.provider`，而后者 import `app.knowledge.service`。
把重排塞进 `search_chunks` 会形成 service → rerank → provider → service 的加载环，
所以重排由调用方显式串起来（`app.agent.graph` 与 `app.api.knowledge`），
`knowledge.service` 不 import 本模块。
"""

from __future__ import annotations

import json
import logging
import urllib.error
from collections.abc import Sequence
from dataclasses import replace

from sqlalchemy.orm import Session

from app import degradation
from app.knowledge.hybrid import carried_evidence
from app.knowledge.service import ChunkResult, RetrievedChunks
from app.llm.provider import chat_completion, rerank_endpoint
from app.settings import Settings
from app.tracing import get_trace_id

logger = logging.getLogger("app.knowledge.rerank")

# 重排专用提示词：与 `GROUNDED_SYSTEM_PROMPT` 那套「只能依据片段、带编号引用」的
# 约束无关——重排只排序、只输出 JSON、不做判断、不生成文本。
RERANK_SYSTEM_PROMPT = (
    "你是检索结果重排器。根据用户问题，判断每个候选片段与问题的相关性，"
    "并按相关度从高到低给出排序。"
    "只输出 JSON，不要输出任何解释、前后缀或代码块，格式为："
    '{"ranking": [{"index": 1, "score": 0.91}, ...]}。'
    "index 是候选片段的序号（从 1 开始），score 是 0 到 1 的相关性（越相关越接近 1）。"
    "不要增删候选、不要改写片段内容、不要回答问题。"
)


def build_rerank_messages(
    query: str, candidates: Sequence[ChunkResult]
) -> list[dict]:
    """组装重排的提示词：系统的排序约束 + 带序号的候选片段与问题。"""
    numbered = "\n".join(
        f"[{index}] {chunk.content}"
        for index, chunk in enumerate(candidates, start=1)
    )
    return [
        {"role": "system", "content": RERANK_SYSTEM_PROMPT},
        {"role": "user", "content": f"问题：{query}\n\n候选片段：\n{numbered}"},
    ]


def parse_ranking(content: str, *, candidate_count: int) -> list[tuple[int, float]]:
    """把模型输出解析成 `[(从 0 起的候选下标, 相关性)]`。

    模型输出是**不可信输入**：越界序号、重复序号、非数值分一律丢弃，相关度截断到
    [0, 1]。结构本身不合预期（不是 JSON、没有 `ranking` 列表、一条可用的都没有）时抛
    `ValueError`——调用方据此走降级，而不是拿一个空排序去覆盖 RRF 序。
    """
    try:
        payload = json.loads(content)
        entries = payload["ranking"]
    except (json.JSONDecodeError, TypeError, KeyError, IndexError) as exc:
        raise ValueError("重排输出不是预期的 JSON 结构") from exc
    if not isinstance(entries, list):
        raise ValueError("重排输出的 ranking 不是列表")

    ranking: list[tuple[int, float]] = []
    seen: set[int] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        try:
            index = int(entry["index"]) - 1
            score = float(entry["score"])
        except (KeyError, TypeError, ValueError):
            continue
        if not 0 <= index < candidate_count or index in seen:
            continue
        seen.add(index)
        ranking.append((index, min(max(score, 0.0), 1.0)))

    if not ranking:
        raise ValueError("重排输出里没有任何可用的候选序号")
    return ranking


def _apply_ranking(
    candidates: Sequence[ChunkResult], ranking: list[tuple[int, float]]
) -> list[ChunkResult]:
    """按模型给的顺序与相关性重排候选，并把相关性写进 `score`。

    模型没提到的候选接在尾部、`score` 记 0.0：成功路径上 `score` 只该有一种量纲
    （模型给的相关性），把召回那一步的归一化 RRF 留在里面会混进跨查询不可比的分，
    而那个分量级（0.94~1.0）还会让「模型没排过的块」在 `fuse_and_rank` 的加权和里
    反超模型排过的块。
    """
    ranked = [replace(candidates[index], score=score) for index, score in ranking]
    ranked_indices = {index for index, _ in ranking}
    ranked.extend(
        replace(chunk, score=0.0)
        for index, chunk in enumerate(candidates)
        if index not in ranked_indices
    )
    return ranked


def protective_threshold(chunk: ChunkResult, settings: Settings) -> float:
    """这个块按哪条阈值算「已达标的块」（Q18 保底占位的判据）。

    `vector` 与 `keyword` 各按自己那条臂的阈值。`hybrid` 是两路都命中的块，而它的
    `evidence_score` 是两路中的较大值——事后已经分不清这个分属于哪条臂的量纲，因此
    按两臂中**较松**的阈值判：保底宁可多占一个名额，也不让一条可能达标的分块被重排
    挤出上下文。
    """
    if chunk.source == "keyword":
        return settings.retrieval_keyword_score_threshold
    if chunk.source == "hybrid":
        return min(
            settings.retrieval_score_threshold,
            settings.retrieval_keyword_score_threshold,
        )
    return settings.retrieval_score_threshold


def assemble_context_with_guarantee(
    ranked: Sequence[ChunkResult], *, settings: Settings, top_k: int
) -> list[ChunkResult]:
    """组装最终上下文：达标块保底占位、未达标块按重排序补足名额（Q18）。

    顺序仍是重排序：一条未达标的块排在达标块之前时它就在前面，只是不挤掉达标块的名额。
    名额装不下全部达标块时按重排序截断——被截掉的仍是排得最靠后的达标块，而不是回到
    「一个达标块都不剩」。若允许重排挤掉全部达标块，就会出现「分臂判定说有依据、送进
    模型的上下文里一个达标块都没有」，那等于让一次增强环节改写了合规结论。
    """
    if top_k <= 0:
        return []

    def _key(chunk: ChunkResult) -> tuple[int, int]:
        return (chunk.knowledge_id, chunk.chunk_index)

    selected = {
        _key(chunk)
        for chunk in ranked
        if chunk.evidence_score >= protective_threshold(chunk, settings)
    }
    for chunk in ranked:
        if len(selected) >= top_k:
            break
        selected.add(_key(chunk))
    return [chunk for chunk in ranked if _key(chunk) in selected][:top_k]


def _should_call_model(settings: Settings) -> bool:
    """是否发起重排调用。三条恒等保序（不发调用）的跳过条件：

    - `rerank_enabled` 为假（运维/演示临时关掉）；
    - `resolved_llm_provider == "fake"`（没有可用模型配置）；
    - `demo_replay`（ADR-0008：回放不发起任何外部调用）。

    跳过的语义是「顺序与 score 都保持召回那一步的结果」，不是降级——它不给
    `biz_degradation_trace` 记账，否则「关掉重排」会被统计成「系统在降级状态下工作」。
    """
    return (
        settings.rerank_enabled
        and settings.resolved_llm_provider != "fake"
        and not settings.demo_replay
    )


def _is_timeout(exc: BaseException | None) -> bool:
    """超时与「不可达」是两种降级原因，统计口径要能分开。"""
    seen: set[int] = set()
    candidate = exc
    while candidate is not None and id(candidate) not in seen:
        seen.add(id(candidate))
        if isinstance(candidate, TimeoutError):
            # socket.timeout 在 3.10+ 就是 TimeoutError 的别名。
            return True
        if isinstance(candidate, urllib.error.URLError) and isinstance(
            candidate.reason, TimeoutError
        ):
            return True
        candidate = candidate.__cause__ or candidate.__context__
    return False


def _model_ranking(
    query: str,
    candidates: Sequence[ChunkResult],
    settings: Settings,
    *,
    db: Session,
    agent_type: str | None,
) -> list[ChunkResult] | None:
    """发一次重排调用并应用结果；任何失败都退回 `None`（调用方保持 RRF 序）。

    超时与重试刻意**不套用主链路**：主链路是「`llm_timeout_seconds`(30s) × (1+3 次
    重试) 再切备用配置」，那是为「回答必须尽量产出」设计的；搬到检索链上会把 2s 的
    检索变成 30s+。重排单次调用、`rerank_timeout_seconds` 超时、不切备用配置——备用
    配置的语义是「主模型不可用时给兜底回答」，不是「重排要更稳」。

    重排与回答生成可以用**不同的模型**：配全 `rerank_llm_*` 三个变量就发独立配置
    （`rerank_endpoint`），没配全回落主配置。换了模型不换失败语义——专用模型失败
    同样走下面的降级退回，不会改用主模型再试一次。
    """
    try:
        content = chat_completion(
            build_rerank_messages(query, candidates),
            settings,
            timeout=settings.rerank_timeout_seconds,
            max_retries=0,
            allow_backup=False,
            endpoint=rerank_endpoint(settings),
        )
        ranking = parse_ranking(content, candidate_count=len(candidates))
    except Exception as exc:  # noqa: BLE001 - 重排边界：任何失败都退回 RRF 序
        reason = (
            degradation.REASON_TIMEOUT
            if _is_timeout(exc)
            else degradation.REASON_UNAVAILABLE
        )
        logger.warning("重排降级（%s）：退回 RRF 序", reason, exc_info=True)
        degradation.record(
            db,
            dependency=degradation.DEPENDENCY_RERANK,
            reason=reason,
            agent_type=agent_type,
            trace_id=get_trace_id(),
            detail=str(exc),
        )
        return None
    return _apply_ranking(candidates, ranking)


def rerank_chunks(
    query: str,
    chunks: Sequence[ChunkResult],
    settings: Settings,
    *,
    db: Session,
    top_k: int,
    agent_type: str | None = None,
) -> RetrievedChunks:
    """重排候选并组装最终上下文：返回至多 `top_k` 条、保持 `ChunkResult` 形状。

    `top_k` 是**最终送进模型的条数**（`AgentConfig.retrieval_top_k`），与召回候选池
    （`hybrid_recall_top_k`）是两个量：先把整池交给重排，再由本函数取货。

    三条路径都返回同样的形状（`RetrievedChunks`，带着召回那一步的臂内证据）：

    - 成功：`score` = 模型给的相关性（0~1），顺序 = 模型给的顺序；
    - 跳过（关闭 / fake / 回放）与降级（超时 / 失败）：顺序 = RRF 序，`score` 保持
      召回那一步写的归一化 RRF 不变（回放模式因此也原样保留预置分，S6）；
    - 两者都走 `assemble_context_with_guarantee` 的保底组装，达标块不会被挤出上下文。

    证据集必须取**调用方传进来的那个对象**（`carried_evidence` 读的是
    `RetrievedChunks.evidence`），不能在 `list()` 出来的副本上取——转成普通 list
    就丢了它，分臂判定会退回「从融合结果反推」那条错路。
    """
    candidates = list(chunks)
    if not candidates:
        return RetrievedChunks([], carried_evidence(chunks))

    ranked: list[ChunkResult] | None = None
    if _should_call_model(settings):
        ranked = _model_ranking(query, candidates, settings, db=db, agent_type=agent_type)
    if ranked is None:
        ranked = candidates

    return RetrievedChunks(
        assemble_context_with_guarantee(ranked, settings=settings, top_k=top_k),
        carried_evidence(chunks),
    )
