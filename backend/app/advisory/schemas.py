from pydantic import BaseModel


class AdvisoryPlanRequest(BaseModel):
    tilt: str | None = None
    advisory_request_id: int | None = None


class AdvisoryReleaseRequest(BaseModel):
    candidates: list[dict] | None = None
    allocation_suggestion: dict[str, float] | None = None
    warnings: list[dict] | None = None


class AdvisoryRejectRequest(BaseModel):
    reason: str | None = None


class AdvisoryCommentRequest(BaseModel):
    body: str | None = None
