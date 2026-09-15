from pydantic import BaseModel, Field


class DraftAnswers(BaseModel):
    answers: dict[str, str] = Field(default_factory=dict)


class SubmitAnswers(BaseModel):
    answers: dict[str, str]
