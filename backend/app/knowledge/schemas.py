from typing import Literal

from pydantic import BaseModel

KnowledgeType = Literal["FAQ", "产品", "政策"]


class DocumentResponse(BaseModel):
    knowledge_id: int
    title: str
    knowledge_type: KnowledgeType
    status: str
    chunk_count: int


class SearchRequest(BaseModel):
    query: str
    knowledge_type: KnowledgeType | None = None
    top_k: int = 5


class ChunkHitResponse(BaseModel):
    knowledge_id: int
    knowledge_type: KnowledgeType
    chunk_index: int
    heading_path: list[str]
    content: str
    score: float
    title: str
    source_file: str


class SearchResponse(BaseModel):
    hits: list[ChunkHitResponse]
