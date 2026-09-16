"""向量检索与图谱检索结果的融合排序（spec「融合排序」）。

融合在这里一次性完成，且发生在生成节点之前——模型看到的是一组已经
按综合分排序、去重过的上下文，不是两组各自独立的结果去自己权衡。
综合分 = vector_weight * 向量分 + graph_weight * 图谱分，两个权重都在
app.settings 里，改权重不改代码（spec「向量与图谱的融合权重可配置」）。
"""

from __future__ import annotations

from dataclasses import replace

from app.knowledge.service import ChunkResult
from app.knowledge_graph.graphrag import GraphPassage

# 图谱段落不对应任何 KnowledgeMeta 记录，用负数 knowledge_id 和查询工具名
# 拼出的 source_file 让它在引用列表里可辨识，同时不会撞上真实文档 id（自增，恒为正）。
_GRAPH_KNOWLEDGE_ID = -1


def _graph_passage_to_chunk(passage: GraphPassage, index: int) -> ChunkResult:
    return ChunkResult(
        knowledge_id=_GRAPH_KNOWLEDGE_ID,
        knowledge_type="graph",
        chunk_index=index,
        heading_path=[passage.entity_type, passage.entity_value],
        content=passage.content,
        score=passage.score,
        title="知识图谱",
        source_file=f"graph:{passage.tool}",
        source="graph",
    )


def _dedupe_key(chunk: ChunkResult) -> tuple:
    # 图谱段落按文本内容去重（不同实体查询可能产出同一条事实）；
    # 向量片段沿用既有的 (knowledge_id, chunk_index) 身份。
    if chunk.source == "graph":
        return ("graph", chunk.content)
    return ("vector", chunk.knowledge_id, chunk.chunk_index)


def fuse_and_rank(
    vector_chunks: list[ChunkResult],
    graph_passages: list[GraphPassage],
    *,
    vector_weight: float,
    graph_weight: float,
) -> list[ChunkResult]:
    if not graph_passages:
        # 没有图谱段落参与融合（四类降级情形都会落到这里）——原样返回向量结果，
        # 不能连 vector_weight 都乘上去。一旦乘了，退化态就不再是「和纯向量检索
        # 一样」，而是「打了折的纯向量检索」：默认权重 0.6/0.4 会把恰好卡在
        # retrieval_score_threshold 之上的向量匹配打到阈值以下，图谱完全没
        # 参与却让原本能生成回答的问题被兜底话术接管，这就不是「增强不是
        # 依赖」了，是依赖坏了会拖累主链路。
        return vector_chunks

    graph_chunks = [_graph_passage_to_chunk(passage, index) for index, passage in enumerate(graph_passages)]

    combined: dict[tuple, ChunkResult] = {}
    combined_scores: dict[tuple, float] = {}

    for chunk in vector_chunks:
        key = _dedupe_key(chunk)
        combined[key] = chunk
        combined_scores[key] = combined_scores.get(key, 0.0) + vector_weight * chunk.score

    for chunk in graph_chunks:
        key = _dedupe_key(chunk)
        combined.setdefault(key, chunk)
        combined_scores[key] = combined_scores.get(key, 0.0) + graph_weight * chunk.score

    ranked_keys = sorted(combined_scores, key=lambda key: combined_scores[key], reverse=True)
    return [replace(combined[key], score=combined_scores[key]) for key in ranked_keys]
