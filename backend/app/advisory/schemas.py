from pydantic import BaseModel


class AdvisoryPlanRequest(BaseModel):
    tilt: str | None = None
