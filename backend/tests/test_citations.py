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
    # 编号重排成回答里的位次，但片段身份不变：第二条引用仍指向第 5 个片段。
    assert text == "答案[1][2]。"
    assert [c.marker for c in citations] == [1, 2]
    assert [(c.knowledge_id, c.chunk_index) for c in citations] == [(1, 0), (3, 0)]


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


def test_a_lone_marker_describes_the_first_source_not_the_fragment_number():
    """整条回答只引了一段时，角标必须是 [1]——模型写的是片段序号。

    片段序号直接显示给客户会出现「只有一个角标、却写着 [3]」：1、2 去了哪里
    无从解释。编号改成回答里的位次后，角标序号即「第几个来源」。
    """
    chunks = [_chunk(1, 0), _chunk(2, 0), _chunk(3, 0)]
    text, citations = reconcile_answer(chunks, [], "该产品暂无公开评级[3]。")

    assert text == "该产品暂无公开评级[1]。"
    assert [c.marker for c in citations] == [1]
    assert (citations[0].knowledge_id, citations[0].chunk_index) == (3, 0)


def test_markers_are_numbered_by_first_appearance_in_the_answer():
    chunks = [_chunk(1, 0), _chunk(2, 0), _chunk(3, 0), _chunk(4, 0)]
    text, citations = reconcile_answer(chunks, [], "先[3]后[2]，再说一次[3]。")

    # 首次出现的顺序即编号顺序；同一片段重复出现沿用同一个编号。
    assert text == "先[1]后[2]，再说一次[1]。"
    assert [c.marker for c in citations] == [1, 2]
    assert [c.knowledge_id for c in citations] == [3, 2]
