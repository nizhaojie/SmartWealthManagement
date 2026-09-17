from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str


class CitationResponse(BaseModel):
    knowledge_id: int
    chunk_index: int
    title: str
    source_file: str
    heading_path: list[str]
    marker: int


class ChatResponse(BaseModel):
    answer: str
    citations: list[CitationResponse]
    intent: str
    content_classification: str
    # 贯穿全链路的追踪标识：客户端拿它就能把一个使用者可见的失败对到日志的具体位置。
    # 它也进 SSE 的 done 帧，于是流式路径与信封式响应携带同一个标识。
    trace_id: str = ""
    # 本轮是否走了降级路径。降级后的回答照常渲染，缺引用也不报错（前端有对应用例），
    # 这个标记只用于让内部使用者知道「这次回答的成色」。
    degraded: bool = False
