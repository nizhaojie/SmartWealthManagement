from datetime import datetime
from typing import Any

from pydantic import BaseModel


class AnalyticsQueryRequest(BaseModel):
    question: str
    # 多轮追问的会话标识：缺省时本轮不带历史，单次提问。
    session_id: str | None = None


class AnalyticsQueryResponse(BaseModel):
    question: str
    sql: str
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    truncated: bool
    views: list[str]
    interpretation: str
    content_classification: str
    disclaimer: str | None


class AnalyticsHistoryItem(BaseModel):
    id: int
    question: str
    sql: str | None
    status: str
    row_count: int | None
    truncated: bool
    error_code: int | None
    create_time: datetime


class AnalyticsExampleItem(BaseModel):
    question: str
