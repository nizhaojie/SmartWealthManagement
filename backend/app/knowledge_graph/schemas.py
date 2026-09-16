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


class HoldingProduct(BaseModel):
    """客户持仓产品工具的单条结果：一笔持仓关联的产品要素。"""

    product_code: str
    product_name: str
    product_type: str
    risk_level: str
    shares: float
    market_value: float


class ProductIndustry(BaseModel):
    """产品所属行业工具的单条结果：行业名称与该产品底层资产在此行业的权重。"""

    industry: str
    weight: float


class ProductSummary(BaseModel):
    """某风险等级的适配产品、基金经理管理的产品两个工具共用的产品要素。"""

    product_code: str
    product_name: str
    product_type: str
    risk_level: str


class CommonHoldingProduct(BaseModel):
    """客户间共同持仓工具的单条结果。"""

    product_code: str
    product_name: str
    product_type: str


class IndustryExposure(BaseModel):
    """客户持仓行业分布工具的单条结果：该行业的持仓市值与占该客户总持仓的比例。"""

    industry: str
    exposure: float
    share: float
