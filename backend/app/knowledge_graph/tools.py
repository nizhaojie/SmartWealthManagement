"""图谱查询工具：Agent 传实体标识，查询语句在这里固定（spec「查询工具」）。

六个工具对应 spec.md「查询工具」小节列出的六类常用查询。每个工具的参数
是实体标识（customer_id、product_code……）而不是查询片段——Agent 不拼
Cypher，这既避免了查询注入，也让图谱结构的变化（改标签名、改关系方向）
只影响这个文件，调用方的参数契约不变。

`driver`/`namespace` 不是实体标识，是调用方（HTTP 层、GraphRAG 编排）
注入的基础设施参数，和 `app.knowledge_graph.sync.rebuild_graph` 的签名
一致——命名空间用来隔离开发/测试图谱（见 app.settings），不是 Agent 要
决定的东西。

超出参数契约的输入（非正数 customer_id、空字符串、不认识的风险等级
代码……）在发出 Cypher 之前就用 `AppError(400, ...)` 拒绝，和仓库里
其余 service 模块校验输入的方式一致（如 app.risk_assessment.service）。
"""

from __future__ import annotations

from neo4j import Driver, ManagedTransaction

from app.exceptions import AppError
from app.knowledge_graph.schemas import (
    CommonHoldingProduct,
    HoldingProduct,
    IndustryExposure,
    ProductIndustry,
    ProductSummary,
)
from app.suitability.rules import PRODUCT_RISK_LEVELS

_CUSTOMER_RISK_LEVELS = tuple(f"C{tier}" for tier in range(1, len(PRODUCT_RISK_LEVELS) + 1))
_TIER_BY_CUSTOMER_RISK_LEVEL: dict[str, int] = {
    code: tier for tier, code in enumerate(_CUSTOMER_RISK_LEVELS, start=1)
}

INVALID_CUSTOMER_ID_MESSAGE = "customer_id 必须是正整数"
EMPTY_PRODUCT_CODE_MESSAGE = "product_code 不能为空"
EMPTY_FUND_MANAGER_MESSAGE = "fund_manager 不能为空"
UNKNOWN_RISK_LEVEL_MESSAGE = "未知的风险等级代码"
SAME_CUSTOMER_MESSAGE = "customer_id_a 与 customer_id_b 不能相同"


def _require_positive_customer_id(customer_id: int) -> int:
    if isinstance(customer_id, bool) or not isinstance(customer_id, int) or customer_id <= 0:
        raise AppError(400, INVALID_CUSTOMER_ID_MESSAGE)
    return customer_id


def _require_nonempty(value: str, message: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AppError(400, message)
    return value.strip()


def _tier_of_customer_risk_level(risk_level: str) -> int:
    tier = _TIER_BY_CUSTOMER_RISK_LEVEL.get(risk_level)
    if tier is None:
        raise AppError(400, UNKNOWN_RISK_LEVEL_MESSAGE)
    return tier


def customer_holdings(
    driver: Driver, *, namespace: str, customer_id: int
) -> list[HoldingProduct]:
    """客户持仓产品：这位客户当前持有哪些产品。"""
    customer_id = _require_positive_customer_id(customer_id)
    with driver.session() as session:
        rows = session.execute_read(_customer_holdings_tx, namespace, customer_id)
    return [HoldingProduct(**row) for row in rows]


def _customer_holdings_tx(tx: ManagedTransaction, namespace: str, customer_id: int) -> list[dict]:
    result = tx.run(
        "MATCH (:Customer {namespace: $ns, customer_id: $customer_id})"
        "-[h:HOLDS]->(p:Product {namespace: $ns}) "
        "RETURN p.product_code AS product_code, p.product_name AS product_name, "
        "p.product_type AS product_type, p.risk_level AS risk_level, "
        "h.shares AS shares, h.market_value AS market_value "
        "ORDER BY p.product_code",
        ns=namespace,
        customer_id=customer_id,
    )
    return [dict(record) for record in result]


def product_industries(
    driver: Driver, *, namespace: str, product_code: str
) -> list[ProductIndustry]:
    """产品所属行业：这只产品的底层资产落在哪些行业，及各自权重。"""
    product_code = _require_nonempty(product_code, EMPTY_PRODUCT_CODE_MESSAGE)
    with driver.session() as session:
        rows = session.execute_read(_product_industries_tx, namespace, product_code)
    return [ProductIndustry(**row) for row in rows]


def _product_industries_tx(
    tx: ManagedTransaction, namespace: str, product_code: str
) -> list[dict]:
    result = tx.run(
        "MATCH (:Product {namespace: $ns, product_code: $product_code})"
        "-[b:BELONGS_TO_INDUSTRY]->(i:Industry {namespace: $ns}) "
        "RETURN i.name AS industry, b.weight AS weight "
        "ORDER BY b.weight DESC, i.name",
        ns=namespace,
        product_code=product_code,
    )
    return [dict(record) for record in result]


def products_for_risk_level(
    driver: Driver, *, namespace: str, risk_level: str
) -> list[ProductSummary]:
    """某风险等级的适配产品：给定客户风险等级代码（C1..C5），返回其可持有的全部产品（R1..Rn）。"""
    tier = _tier_of_customer_risk_level(risk_level)
    with driver.session() as session:
        rows = session.execute_read(_products_for_risk_level_tx, namespace, tier)
    return [ProductSummary(**row) for row in rows]


def _products_for_risk_level_tx(tx: ManagedTransaction, namespace: str, tier: int) -> list[dict]:
    result = tx.run(
        "MATCH (p:Product {namespace: $ns})-[:SUITABLE_FOR]->(:RiskLevel {namespace: $ns, tier: $tier}) "
        "RETURN p.product_code AS product_code, p.product_name AS product_name, "
        "p.product_type AS product_type, p.risk_level AS risk_level "
        "ORDER BY p.product_code",
        ns=namespace,
        tier=tier,
    )
    return [dict(record) for record in result]


def customer_industry_exposure(
    driver: Driver, *, namespace: str, customer_id: int
) -> list[IndustryExposure]:
    """客户持仓的行业分布：按持仓市值 × 行业权重聚合，按市值降序返回。"""
    customer_id = _require_positive_customer_id(customer_id)
    with driver.session() as session:
        rows = session.execute_read(_customer_industry_exposure_tx, namespace, customer_id)
    total = sum(row["exposure"] for row in rows)
    return [
        IndustryExposure(
            industry=row["industry"],
            exposure=row["exposure"],
            share=(row["exposure"] / total) if total else 0.0,
        )
        for row in rows
    ]


def _customer_industry_exposure_tx(
    tx: ManagedTransaction, namespace: str, customer_id: int
) -> list[dict]:
    result = tx.run(
        "MATCH (:Customer {namespace: $ns, customer_id: $customer_id})"
        "-[h:HOLDS]->(:Product {namespace: $ns})"
        "-[b:BELONGS_TO_INDUSTRY]->(i:Industry {namespace: $ns}) "
        "RETURN i.name AS industry, sum(h.market_value * b.weight) AS exposure "
        "ORDER BY exposure DESC, industry",
        ns=namespace,
        customer_id=customer_id,
    )
    return [dict(record) for record in result]


def common_holdings(
    driver: Driver, *, namespace: str, customer_id_a: int, customer_id_b: int
) -> list[CommonHoldingProduct]:
    """客户间共同持仓：两位客户同时持有的产品。"""
    customer_id_a = _require_positive_customer_id(customer_id_a)
    customer_id_b = _require_positive_customer_id(customer_id_b)
    if customer_id_a == customer_id_b:
        raise AppError(400, SAME_CUSTOMER_MESSAGE)
    with driver.session() as session:
        rows = session.execute_read(
            _common_holdings_tx, namespace, customer_id_a, customer_id_b
        )
    return [CommonHoldingProduct(**row) for row in rows]


def _common_holdings_tx(
    tx: ManagedTransaction, namespace: str, customer_id_a: int, customer_id_b: int
) -> list[dict]:
    result = tx.run(
        "MATCH (:Customer {namespace: $ns, customer_id: $a})-[:HOLDS]->(p:Product {namespace: $ns})"
        "<-[:HOLDS]-(:Customer {namespace: $ns, customer_id: $b}) "
        "RETURN DISTINCT p.product_code AS product_code, p.product_name AS product_name, "
        "p.product_type AS product_type "
        "ORDER BY p.product_code",
        ns=namespace,
        a=customer_id_a,
        b=customer_id_b,
    )
    return [dict(record) for record in result]


def fund_manager_products(
    driver: Driver, *, namespace: str, fund_manager: str
) -> list[ProductSummary]:
    """基金经理管理的产品：这位基金经理名下的全部产品。"""
    fund_manager = _require_nonempty(fund_manager, EMPTY_FUND_MANAGER_MESSAGE)
    with driver.session() as session:
        rows = session.execute_read(_fund_manager_products_tx, namespace, fund_manager)
    return [ProductSummary(**row) for row in rows]


def _fund_manager_products_tx(
    tx: ManagedTransaction, namespace: str, fund_manager: str
) -> list[dict]:
    result = tx.run(
        "MATCH (:FundManager {namespace: $ns, name: $name})"
        "<-[:MANAGED_BY]-(p:Product {namespace: $ns}) "
        "RETURN p.product_code AS product_code, p.product_name AS product_name, "
        "p.product_type AS product_type, p.risk_level AS risk_level "
        "ORDER BY p.product_code",
        ns=namespace,
        name=fund_manager,
    )
    return [dict(record) for record in result]
