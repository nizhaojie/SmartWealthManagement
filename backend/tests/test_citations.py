"""`reconcile_answer` 的单元测试：正文 [N] 角标与引用块的对齐。

这一层解决「正文写 [5]、模型 citations 字段却漏报」这类角标悬空，以及
「正文写 [99]、但没有第 99 个分块」这类编造引用——见 app.agent.citations。
"""

from app.agent.citations import reconcile_answer
from app.knowledge.service import ChunkResult


def _chunk(knowledge_id: int, chunk_index: int, content: str = "片段") -> ChunkResult:
    return ChunkResult(
        knowledge_id=knowledge_id,
        knowledge_type="FAQ",
        chunk_index=chunk_index,
        heading_path=[],
        content=content,
        score=1.0,
        title="标题",
        source_file="f.txt",
        evidence_score=1.0,
    )


def test_markers_in_text_match_citations():
    chunks = [_chunk(1, 0), _chunk(1, 1), _chunk(2, 0)]
    text, citations = reconcile_answer(chunks, [1, 2], "答案[1]和[2]。")
    assert text == "答案[1]和[2]。"
    assert [c.marker for c in citations] == [1, 2]


def test_body_marker_not_reported_by_model_still_gets_a_citation():
    # 正文写 [5]、模型 citations 字段漏报——信正文，补上引用块。
    chunks = [_chunk(1, 0), _chunk(1, 1), _chunk(2, 0), _chunk(2, 1), _chunk(3, 0)]
    text, citations = reconcile_answer(chunks, [1, 2], "答案[1][5]。")
    assert text == "答案[1][5]。"
    assert [c.marker for c in citations] == [1, 5]


def test_out_of_range_marker_is_stripped_from_text():
    chunks = [_chunk(1, 0)]
    text, citations = reconcile_answer(chunks, [1, 99], "内容[1][99]。")
    assert text == "内容[1]。"
    assert [c.marker for c in citations] == [1]


def test_duplicate_marker_is_kept_once_in_citations():
    chunks = [_chunk(1, 0), _chunk(1, 1)]
    text, citations = reconcile_answer(chunks, [1], "答案[1][1]。")
    assert text == "答案[1][1]。"
    assert [c.marker for c in citations] == [1]


def test_no_markers_falls_back_to_cited_numbers():
    chunks = [_chunk(1, 0), _chunk(1, 1)]
    text, citations = reconcile_answer(chunks, [1, 2], "纯文本回答。")
    assert text == "纯文本回答。"
    assert [c.marker for c in citations] == [1, 2]
