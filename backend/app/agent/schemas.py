from typing import Any

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


class DataAnswerColumn(BaseModel):
    """结果表的一列：给人看的表头（中文）与它取自哪一列。"""

    key: str
    label: str


class DataAnswerResponse(BaseModel):
    """客户侧的一张小表（ADR-0028）。

    它是一份**客户契约**，不是内部 ``AnalyticsQueryResponse`` 的裁剪版：不含 SQL、
    不含 ``va_*`` 视图名（``views`` 是中文名）、不含 ``customer_id`` 列，英文列名只
    出现在 ``columns[].key`` 里（前端用它算键，不显示）。``row_count`` 是**已返回**
    的行数，是否被行数上限截断由 ``truncated`` 表达。
    """

    columns: list[DataAnswerColumn]
    # 拉链式二维数组：每行的值与 ``columns`` 一一对应，值一律是 JSON 可序列化的
    # （``execution._json_value`` 已把 Decimal / 日期 / 字节换成基本类型）。
    rows: list[list[Any]]
    row_count: int
    truncated: bool
    views: list[str]


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
    # 数据查询分支「有行」时的结果表（ADR-0028）。零行、失败/超时、白名单外三种出口
    # 都是 None——一张空表会把「没有数据」与「查询挂了」在观感上抹平。它随信封式响应
    # 与 SSE 的 done 帧一起走，因此两个端点拿到的形状一致。
    data_answer: DataAnswerResponse | None = None
