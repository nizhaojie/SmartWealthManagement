"""关键词召回臂的分词与两路召回的 RRF 融合（ADR-0022）。

这里的两个函数都是纯函数：只依赖 `ChunkResult` 的形状，不碰数据库、不碰模型，
因此可以被单测直接钉住。检索编排（哪几路并行、超时怎么降级）留在
`app.knowledge.service`，本模块只管「怎么分词」与「怎么把位次合成一个顺序」。
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from dataclasses import replace
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

import jieba

if TYPE_CHECKING:  # 只为类型标注：运行期只用到 ChunkResult 的 dataclass 行为，
    # 真去 import 它会形成 service ↔ hybrid 的模块加载环。
    from app.knowledge.service import ChunkResult

logger = logging.getLogger("app.knowledge.hybrid")

# jieba 首次分词会构建前缀词典并往 stderr 打一行进度；它对服务日志没有价值，
# 这里抬到 WARNING，避免每次冷启动都刷一段看似异常的构建信息。
jieba.setLogLevel(logging.WARNING)


@lru_cache(maxsize=None)
def _load_user_dict(path: str) -> None:
    """可选的用户词典（Q16 只预留路径，本 slice 不提供词表）：文件不存在就跳过。

    用 `lru_cache` 保证同一个词表只加载一次——`jieba.load_userdict` 每次调用都会
    往全局词典里追加，重复加载会不断放大同一个词条的分词权重。
    """
    if path and Path(path).is_file():
        jieba.load_userdict(path)


def tokenize(text: str, *, user_dict_path: str = "") -> list[str]:
    """查询侧与文档侧共用的分词：`jieba.lcut` 精确模式，丢掉纯空白与纯标点 token。

    两侧必须是同一个分词器、同一种模式，否则 BM25 的词表对不上。纯空白与纯标点
    只贡献噪声 df，直接丢弃；「七日 / 年化」这类切分由 jieba 的词典决定，不在这里
    人为干预（Q16：不建自定义金融词典，只预留上面那条用户词典路径）。
    """
    if user_dict_path:
        _load_user_dict(user_dict_path)
    return [token for token in jieba.lcut(text) if any(char.isalnum() for char in token)]


def arm_evidence(chunks: Iterable[ChunkResult]) -> dict[str, float]:
    """从带来源标记的候选里取各召回臂的最高原始分（分臂判定的输入）。

    **在两路还分着的时候**（`search_chunks` 内、RRF 之前）调用才是准确的：那时每个
    块的 `evidence_score` 恰好就是它那条臂的分，`source` 也只有 vector / keyword
    两个取值。RRF 把 hybrid 块两路取大之后再用它反推，会把 BM25 的量纲记进向量臂
    （无关问题的 BM25 也能到个位数，而余弦阈值是 0.55），所以在线上路径上优先用
    `RetrievedChunks.evidence`；这个函数是「调用方给的是普通 list」时的退路。
    """
    evidence = {"vector": 0.0, "keyword": 0.0, "graph": 0.0}
    for chunk in chunks:
        if chunk.source in ("vector", "hybrid"):
            evidence["vector"] = max(evidence["vector"], chunk.evidence_score)
        if chunk.source in ("keyword", "hybrid"):
            evidence["keyword"] = max(evidence["keyword"], chunk.evidence_score)
    return evidence


def carried_evidence(chunks: Iterable[ChunkResult]) -> dict[str, float]:
    """取分臂判定的输入：优先用 `RetrievedChunks.evidence`，普通 list 才退到反推。

    检索那一步（两路还分着的时候）算好的臂内最高分是权威值；重排与融合之后按
    `source` 反推只对单臂构造的候选成立（hybrid 块的 `evidence_score` 是两路取大，
    反推会把 BM25 的量纲记进向量臂）。这里收拢成一个函数，避免「往回退」和「带出来」
    两条路各写一遍——`rerank` 与 `agent.graph` 的分臂证据都用它。
    """
    carried = getattr(chunks, "evidence", None)
    return dict(carried) if carried is not None else arm_evidence(chunks)


def rrf_fuse(
    arms: Sequence[Sequence[ChunkResult]],
    *,
    rrf_k: int,
    top_k: int,
) -> list[ChunkResult]:
    """按位次融合各路召回（Reciprocal Rank Fusion），返回重排后的候选。

    - 融合分 = `Σ 1/(rrf_k + rank_arm)`，`rank_arm` 从 1 起。RRF 只用位次，
      因此天然跨量纲，免去「余弦与 BM25 怎么归一化」这个无底洞。
    - 去重身份是 `(knowledge_id, chunk_index)`：两路都命中的块只出现一次，
      `source` 标 `"hybrid"`、`evidence_score` 取两路里的较大值（分臂判定用）。
    - `score` 写**归一化 RRF**（本次候选的最高分记 1.0，其余按比例）：它仍与图谱
      分（1.0）同一量纲、单调不增，下游的加权融合因此继续成立。它跨查询不可比，
      要展示「这条有多相关」应当读 `evidence_score`。
    """
    scores: dict[tuple[int, int], float] = {}
    groups: dict[tuple[int, int], list[ChunkResult]] = {}
    for arm in arms:
        for rank, chunk in enumerate(arm, start=1):
            key = (chunk.knowledge_id, chunk.chunk_index)
            scores[key] = scores.get(key, 0.0) + 1.0 / (rrf_k + rank)
            groups.setdefault(key, []).append(chunk)

    if not scores:
        return []

    best = max(scores.values())
    ranked_keys = sorted(scores, key=lambda key: (-scores[key], key[0], key[1]))
    return [
        _merge(groups[key], score=scores[key] / best) for key in ranked_keys[:top_k]
    ]


def _merge(group: list[ChunkResult], *, score: float) -> ChunkResult:
    representative = group[0]
    return replace(
        representative,
        score=score,
        source="hybrid" if len(group) > 1 else representative.source,
        evidence_score=max(chunk.evidence_score for chunk in group),
    )
