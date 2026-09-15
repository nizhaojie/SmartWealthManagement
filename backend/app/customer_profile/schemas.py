from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class WriteTagRequest(BaseModel):
    tag_key: str
    value: Any
    source: str
    reason: str | None = Field(default=None)
