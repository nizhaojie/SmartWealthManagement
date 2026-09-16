from typing import Any

from pydantic import BaseModel


class AnalyticsQueryRequest(BaseModel):
    question: str


class AnalyticsQueryResponse(BaseModel):
    question: str
    sql: str
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    truncated: bool
    views: list[str]
