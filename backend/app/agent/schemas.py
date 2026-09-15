from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str


class CitationResponse(BaseModel):
    knowledge_id: int
    chunk_index: int
    title: str
    source_file: str
    heading_path: list[str]


class ChatResponse(BaseModel):
    answer: str
    citations: list[CitationResponse]
    intent: str
    content_classification: str
