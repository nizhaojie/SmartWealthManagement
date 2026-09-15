from dataclasses import dataclass

from app.knowledge.service import ChunkResult


@dataclass
class Citation:
    knowledge_id: int
    chunk_index: int
    title: str
    source_file: str
    heading_path: list[str]


def build_citations(chunks: list[ChunkResult], cited_chunk_numbers: list[int]) -> list[Citation]:
    """把模型输出的引用序号（1-based，对应 chunks 列表位置）映射为结构化引用。

    序号在本次检索结果范围之外的一律剔除——模型编出一个不存在的引用，
    不能让它蒙混过关变成看起来有依据的角标。
    """
    citations: list[Citation] = []
    seen: set[tuple[int, int]] = set()
    for number in cited_chunk_numbers:
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
            )
        )
    return citations
