from pydantic import BaseModel


class AdvisoryRequestCreate(BaseModel):
    product_type: str | None = None
    risk_level: str | None = None
    min_amount: str | None = None
    min_expected_return: str | None = None
    max_term_days: str | None = None
