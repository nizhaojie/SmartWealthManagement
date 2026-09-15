from datetime import datetime
from typing import Literal

from pydantic import BaseModel

KnowledgeType = Literal["FAQ", "产品", "政策"]
DocumentStatus = Literal["processing", "active", "failed", "expired"]
IngestStage = Literal["parse", "chunk", "embed", "store"]


class DocumentResponse(BaseModel):
    knowledge_id: int
    knowledge_type: KnowledgeType
    title: str
    source_file: str
    version: str
    status: DocumentStatus
    chunk_count: int
    expire_at: datetime | None
    create_time: datetime
    stage: IngestStage | None = None
    failure_reason: str | None = None


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
