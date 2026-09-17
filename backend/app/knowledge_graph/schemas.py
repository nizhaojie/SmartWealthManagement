from datetime import datetime
from typing import Any

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


class GraphNode(BaseModel):
    """客户关系图（ticket 04）里的一个节点：客户、产品、行业、基金经理四类之一。

    `attrs` 按节点类型放不同字段，供前端点击节点时原样展示，不必为每种
    类型单开一个 schema。`marked` 只对行业节点有意义（持仓集中度超阈值），
    其余类型恒为 False。
    """

    id: str
    type: str
    label: str
    attrs: dict[str, Any]
    marked: bool = False


class GraphEdge(BaseModel):
    """客户关系图里的一条连线：HOLDS / BELONGS_TO_INDUSTRY / MANAGED_BY 之一。"""

    source: str
    target: str
    type: str


class CustomerGraphView(BaseModel):
    """客户关系图接口的响应体：默认两跳（客户→产品→行业），基金经理按需展开。

    `degraded` 为真时 nodes/edges 是空的：图谱查询超时或不可用，界面此时应当显示
    「图谱暂时不可用」而不是把异常抛给使用者，也不能把空图误读成「这位客户没有持仓」。
    """

    customer_id: int
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    synced_at: datetime | None
    degraded: bool = False
