from datetime import datetime

from pydantic import BaseModel


class GraphSyncStatusResponse(BaseModel):
    running: bool
    node_count: int | None
    relationship_count: int | None
    synced_at: datetime | None
    duration_ms: int | None
    last_attempt_status: str | None
    last_attempt_failure_reason: str | None
