"""向量与图谱结果的融合排序（ticket 03「融合排序」），纯函数，不需要真实基础设施。"""

from dataclasses import replace

from app.agent.fusion import fuse_and_rank
from app.knowledge.service import ChunkResult
from app.knowledge_graph.graphrag import GraphPassage


def _vector_chunk(*, knowledge_id: int, chunk_index: int, content: str, score: float) -> ChunkResult:
    return ChunkResult(
        knowledge_id=knowledge_id,
        knowledge_type="FAQ",
        chunk_index=chunk_index,
        heading_path=[],
        content=content,
        score=score,
        title="FAQ 文档",
        source_file="faq.txt",
    )


def _graph_passage(*, content: str, score: float) -> GraphPassage:
    return GraphPassage(
        content=content, score=score, entity_type="customer", entity_value="张三", tool="customer_holdings"
    )


def test_fusion_ranks_by_weighted_combined_score_descending():
    vector_chunks = [_vector_chunk(knowledge_id=1, chunk_index=0, content="向量片段", score=0.5)]
    graph_passages = [_graph_passage(content="图谱事实", score=1.0)]

    ranked = fuse_and_rank(
        vector_chunks, graph_passages, vector_weight=0.6, graph_weight=0.4
    )

    assert [chunk.content for chunk in ranked] == ["图谱事实", "向量片段"]
    assert ranked[0].score == 0.4
    assert ranked[1].score == 0.3


def test_changing_weights_changes_result_order():
    vector_chunks = [_vector_chunk(knowledge_id=1, chunk_index=0, content="向量片段", score=0.5)]
    graph_passages = [_graph_passage(content="图谱事实", score=0.6)]

    ranked_favoring_graph = fuse_and_rank(
        vector_chunks, graph_passages, vector_weight=0.3, graph_weight=0.7
    )
    ranked_favoring_vector = fuse_and_rank(
        vector_chunks, graph_passages, vector_weight=0.9, graph_weight=0.1
    )

    assert [chunk.content for chunk in ranked_favoring_graph] == ["图谱事实", "向量片段"]
    assert [chunk.content for chunk in ranked_favoring_vector] == ["向量片段", "图谱事实"]


def test_fusion_dedupes_identical_graph_passages_from_different_queries():
    graph_passages = [
        _graph_passage(content="重复的图谱事实", score=1.0),
        _graph_passage(content="重复的图谱事实", score=1.0),
        _graph_passage(content="独有的图谱事实", score=1.0),
    ]

    ranked = fuse_and_rank([], graph_passages, vector_weight=0.6, graph_weight=0.4)

    assert len(ranked) == 2
    assert {chunk.content for chunk in ranked} == {"重复的图谱事实", "独有的图谱事实"}


def test_fusion_keeps_similarity_chunk_dedupe_key_by_knowledge_id_and_chunk_index():
    # 去重身份是「哪个分块」而不是「哪条路径」（ADR-0022）：向量 / 关键词 / hybrid
    # 都按 (knowledge_id, chunk_index) 认同一块，融合不会把同块拆成两条。
    vector_chunks = [
        _vector_chunk(knowledge_id=1, chunk_index=0, content="片段A", score=0.9),
        _vector_chunk(knowledge_id=1, chunk_index=1, content="片段B", score=0.8),
    ]

    ranked = fuse_and_rank(vector_chunks, [], vector_weight=0.6, graph_weight=0.4)

    assert [chunk.content for chunk in ranked] == ["片段A", "片段B"]


def test_fusion_preserves_evidence_score_and_source_of_each_chunk():
    # 融合只重写 `score`（加权和），证据分与来源必须原样带过去——兜底判定与
    # 调试留痕读的是它们，融合把它们洗掉就等于把分臂判定弄瞎。
    hybrid = replace(
        _vector_chunk(knowledge_id=1, chunk_index=0, content="两路都命中的片段", score=0.9),
        source="hybrid",
        evidence_score=8.0,
    )

    ranked = fuse_and_rank(
        [hybrid], [_graph_passage(content="图谱事实", score=1.0)],
        vector_weight=0.6, graph_weight=0.4,
    )

    chunk = next(item for item in ranked if item.content == "两路都命中的片段")
    assert chunk.source == "hybrid"
    assert chunk.evidence_score == 8.0


def test_fusion_with_no_graph_passages_returns_vector_chunks_unchanged():
    # search_chunks 已经保证向量结果按相似度降序排列（见 app.agent.graph 的
    # route_after_retrieve 注释）；没有图谱段落参与时融合是纯粹的直通，
    # 不重新排序、不重新计分——见 test_fusion_does_not_deflate_vector_score_when_graph_degrades。
    vector_chunks = [
        _vector_chunk(knowledge_id=2, chunk_index=0, content="高分片段", score=0.8),
        _vector_chunk(knowledge_id=1, chunk_index=0, content="低分片段", score=0.2),
    ]

    ranked = fuse_and_rank(vector_chunks, [], vector_weight=0.6, graph_weight=0.4)

    assert ranked == vector_chunks


def test_fusion_does_not_deflate_vector_score_when_graph_degrades():
    # 回归用例：图谱降级（四类情形之一）时 graph_passages 恒为 []。融合不能因此
    # 把 vector_weight（默认 0.6）乘上向量原始分——0.5 * 0.6 = 0.3 会把分数打出
    # 类似「低于阈值」的样子。图谱是增强，不是依赖：没有图谱段落参与融合时，
    # 向量结果必须和融合之前完全一样，包括分数本身。
    # （兜底判定另用融合前的 retrieval_score，见 app.agent.graph；这条用例守住的是
    # 融合本身不得擅自改动向量分这一半。）
    vector_chunks = [_vector_chunk(knowledge_id=1, chunk_index=0, content="向量片段", score=0.5)]

    ranked = fuse_and_rank(vector_chunks, [], vector_weight=0.6, graph_weight=0.4)

    assert ranked == vector_chunks
    assert ranked[0].score == 0.5
