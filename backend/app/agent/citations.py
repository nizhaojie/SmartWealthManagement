import re
from dataclasses import dataclass

from app.knowledge.service import ChunkResult


@dataclass
class Citation:
    knowledge_id: int
    chunk_index: int
    title: str
    source_file: str
    heading_path: list[str]
    marker: int


# 回答正文里的引用角标：[1]、[2]……。正文是客户实际读到的内容，因此它是
# 「哪些引用该展示」的权威来源；模型自报的 citations 列表只是它对自己输出
# 的复述，两者不一致时信正文（见 `reconcile_answer`）。
_CITATION_MARKER = re.compile(r"\[(\d+)\]")


def _markers_in_text(text: str) -> list[int]:
    """按出现顺序提取正文里的 [N] 角标，去重。"""
    markers: list[int] = []
    seen: set[int] = set()
    for match in _CITATION_MARKER.finditer(text):
        number = int(match.group(1))
        if number not in seen:
            seen.add(number)
            markers.append(number)
    return markers


def _build_from_numbers(chunks: list[ChunkResult], numbers: list[int]) -> list[Citation]:
    """把 1-based 序号列表映射为结构化引用。

    序号在本次检索结果范围之外的一律剔除——模型编出一个不存在的引用，
    不能让它蒙混过关变成看起来有依据的角标。`marker` 原样保留这个序号，
    前端据此把回答文本里的 [N] 角标与结构化引用精确对应，而不必假设
    两者出现的顺序一致。
    """
    citations: list[Citation] = []
    seen: set[tuple[int, int]] = set()
    for number in numbers:
        index = number - 1
        if index < 0 or index >= len(chunks):
            continue
        chunk = chunks[index]
        key = (chunk.knowledge_id, chunk.chunk_index)
        if key in seen:
            continue
        seen.add(key)
        citations.append(
            Citation(
                knowledge_id=chunk.knowledge_id,
                chunk_index=chunk.chunk_index,
                title=chunk.title,
                source_file=chunk.source_file,
                heading_path=chunk.heading_path,
                marker=number,
            )
        )
    return citations


def build_citations(chunks: list[ChunkResult], cited_chunk_numbers: list[int]) -> list[Citation]:
    """按模型自报的引用序号（1-based）构建结构化引用。

    这是 `reconcile_answer` 的退化兜底：只在正文里一个角标都没有时使用
    （模型报了 citations 却忘了在正文里写 [N] 的退化输出）。正常路径请走
    `reconcile_answer`——它把正文角标与引用块对齐，避免「正文写 [5]、引用
    列表却没有 5」这类角标悬空。
    """
    return _build_from_numbers(chunks, cited_chunk_numbers)


def _strip_unmapped_markers(text: str, *, keep: set[int]) -> str:
    """剔除正文里没有对应引用块的 [N] 角标，`keep` 之外的序号整体删掉。"""
    return _CITATION_MARKER.sub(
        lambda match: match.group(0) if int(match.group(1)) in keep else "",
        text,
    )


def reconcile_answer(
    chunks: list[ChunkResult],
    cited_chunk_numbers: list[int],
    answer_text: str,
) -> tuple[str, list[Citation]]:
    """正文 [N] 角标与引用块的双向对齐，返回 (清理后的正文, 引用列表)。

    不变式：回答正文里出现的每个 [N] 角标，都恰好对应一条 `marker == N` 的
    引用；反之亦然。做法是把**正文当成权威**——客户读到的是正文，不是模型
    自报的 citations 字段：

    - 正文里出现、且 N 映射到有效分块（1 ≤ N ≤ len(chunks)）→ 生成引用块；
    - 正文里出现、但越界或无对应分块的 [N] → 从正文剔除，不给它「看似有
      依据」的机会（模型编出一个不存在的引用）；
    - 正文一个角标都没有 → 退回 `cited_chunk_numbers`（模型报了引用却忘了
      写角标的退化输出），此时正文原样返回、不做删减。
    """
    markers = _markers_in_text(answer_text)
    if not markers:
        return answer_text, build_citations(chunks, cited_chunk_numbers)

    citations = _build_from_numbers(chunks, markers)
    kept = {citation.marker for citation in citations}
    return _strip_unmapped_markers(answer_text, keep=kept), citations
