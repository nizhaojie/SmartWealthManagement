"""MySQL → Neo4j 单向投影同步：全量重建，幂等（ADR-0002）。

图谱不是第二个写入源——这里只读 MySQL，从不反向写回。每次重建都是
「删光这个命名空间下的一切，再照 MySQL 当前状态重新建」，不做增量。
删除与重建在同一个 Neo4j 写事务里完成：事务提交前，别的会话读到的还是
旧图谱（Neo4j 的隔离保证）；事务中途出错则整体回滚，旧图谱原封不动。
这就是「重建期间旧图谱可用、失败时旧图谱仍可用」的来源，不需要额外
实现版本号切换。

`namespace` 把同一个 Neo4j 实例里的开发数据与测试数据分开（Neo4j
Community 版不能像 MySQL 那样建两个库，见 app.settings）——每个节点与
关系都带这个属性，重建只删除/创建本命名空间下的内容。

节点与关系的规模统计直接从 MySQL 投影的行数算出，不必重建后再查一遍
Neo4j——CREATE 要么在事务里全部成功，要么整体回滚，两者从不出现「部分
成功」的中间态需要对账。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import TypedDict

from neo4j import Driver, ManagedTransaction
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.customer_assets.service import HELD_STATUS
from app.db.models import Customer, CustomerProfile, Holding, Product, ProductUnderlying, UnderlyingAsset
from app.suitability.rules import PRODUCT_RISK_LEVELS, allowed_product_risk_levels

RISK_TIERS: tuple[int, ...] = tuple(range(1, len(PRODUCT_RISK_LEVELS) + 1))
_RISK_LEVEL_ROWS = [
    {"tier": tier, "customer_risk_level": f"C{tier}", "product_risk_level": f"R{tier}"}
    for tier in RISK_TIERS
]

_INDEX_STATEMENTS = (
    "CREATE INDEX graph_customer_lookup IF NOT EXISTS "
    "FOR (c:Customer) ON (c.namespace, c.customer_id)",
    "CREATE INDEX graph_product_lookup IF NOT EXISTS "
    "FOR (p:Product) ON (p.namespace, p.product_code)",
    "CREATE INDEX graph_risk_level_lookup IF NOT EXISTS "
    "FOR (r:RiskLevel) ON (r.namespace, r.tier)",
    "CREATE INDEX graph_industry_lookup IF NOT EXISTS "
    "FOR (i:Industry) ON (i.namespace, i.name)",
    "CREATE INDEX graph_fund_manager_lookup IF NOT EXISTS "
    "FOR (m:FundManager) ON (m.namespace, m.name)",
)


class GraphStats(TypedDict):
    node_count: int
    relationship_count: int


@dataclass
class _Projection:
    customers: list[dict] = field(default_factory=list)
    products: list[dict] = field(default_factory=list)
    industries: list[str] = field(default_factory=list)
    fund_managers: list[str] = field(default_factory=list)
    holdings: list[dict] = field(default_factory=list)
    customer_risk_levels: list[dict] = field(default_factory=list)
    product_industries: list[dict] = field(default_factory=list)
    product_fund_managers: list[dict] = field(default_factory=list)
    product_suitability: list[dict] = field(default_factory=list)


def _tier_of(risk_code: str) -> int:
    return int(risk_code[1:])


def _load_projection(db: Session) -> _Projection:
    customers = [
        {"customer_id": row.id, "real_name": row.real_name, "customer_level": row.customer_level}
        for row in db.execute(select(Customer.id, Customer.real_name, Customer.customer_level)).all()
    ]

    customer_risk_levels = [
        {"customer_id": row.customer_id, "tier": _tier_of(row.risk_level)}
        for row in db.execute(
            select(CustomerProfile.customer_id, CustomerProfile.risk_level)
        ).all()
    ]

    product_rows = db.execute(
        select(
            Product.product_code,
            Product.product_name,
            Product.product_type,
            Product.risk_level,
            Product.status,
            Product.fund_manager,
        )
    ).all()
    products = [
        {
            "product_code": row.product_code,
            "product_name": row.product_name,
            "product_type": row.product_type,
            "risk_level": row.risk_level,
            "status": row.status,
        }
        for row in product_rows
    ]
    product_fund_managers = [
        {"product_code": row.product_code, "fund_manager": row.fund_manager}
        for row in product_rows
        if row.fund_manager
    ]
    fund_managers = sorted({row["fund_manager"] for row in product_fund_managers})

    # Cn 客户只能持有 R1..Rn 产品（app.suitability.rules）——反过来，产品风险等级
    # 为 Rn 的产品适合 tier >= n 的所有客户。复用同一条规则，图谱与适当性判定不会走岔。
    product_suitability = [
        {"product_code": row.product_code, "tier": tier}
        for row in product_rows
        for tier in RISK_TIERS
        if row.risk_level in allowed_product_risk_levels(f"C{tier}")
    ]

    holdings = [
        {
            "customer_id": row.customer_id,
            "product_code": row.product_code,
            "shares": float(row.shares),
            "market_value": float(row.current_value),
        }
        for row in db.execute(
            select(Holding.customer_id, Product.product_code, Holding.shares, Holding.current_value)
            .join(Product, Product.id == Holding.product_id)
            .where(Holding.status == HELD_STATUS)
        ).all()
    ]

    # 行业只看产品直接持有的底层资产，不递归穿透嵌套产品——递归穿透是
    # app.customer_assets.look_through 的职责（MySQL 递归 CTE，ADR-0002），
    # 图谱这条路径负责的是行业关联与多跳查询，两者不重复实现同一段逻辑。
    underlying_rows = db.execute(
        select(Product.product_code, UnderlyingAsset.industry, ProductUnderlying.weight)
        .join(ProductUnderlying, ProductUnderlying.product_id == Product.id)
        .join(UnderlyingAsset, UnderlyingAsset.id == ProductUnderlying.underlying_asset_id)
        .where(ProductUnderlying.underlying_asset_id.is_not(None))
    ).all()
    industry_totals: dict[tuple[str, str], Decimal] = {}
    for row in underlying_rows:
        key = (row.product_code, row.industry)
        industry_totals[key] = industry_totals.get(key, Decimal("0")) + row.weight
    product_industries = [
        {"product_code": code, "industry": industry, "weight": float(weight)}
        for (code, industry), weight in industry_totals.items()
    ]
    industries = sorted({industry for _, industry in industry_totals})

    return _Projection(
        customers=customers,
        products=products,
        industries=industries,
        fund_managers=fund_managers,
        holdings=holdings,
        customer_risk_levels=customer_risk_levels,
        product_industries=product_industries,
        product_fund_managers=product_fund_managers,
        product_suitability=product_suitability,
    )


def _apply_rebuild(tx: ManagedTransaction, namespace: str, projection: _Projection) -> GraphStats:
    tx.run("MATCH (n {namespace: $ns}) DETACH DELETE n", ns=namespace)

    tx.run(
        "UNWIND $rows AS row "
        "CREATE (:Customer {namespace: $ns, customer_id: row.customer_id, "
        "real_name: row.real_name, customer_level: row.customer_level})",
        ns=namespace,
        rows=projection.customers,
    )
    tx.run(
        "UNWIND $rows AS row "
        "CREATE (:Product {namespace: $ns, product_code: row.product_code, "
        "product_name: row.product_name, product_type: row.product_type, "
        "risk_level: row.risk_level, status: row.status})",
        ns=namespace,
        rows=projection.products,
    )
    tx.run(
        "UNWIND $rows AS row "
        "CREATE (:RiskLevel {namespace: $ns, tier: row.tier, "
        "customer_risk_level: row.customer_risk_level, "
        "product_risk_level: row.product_risk_level})",
        ns=namespace,
        rows=_RISK_LEVEL_ROWS,
    )
    tx.run(
        "UNWIND $rows AS row CREATE (:Industry {namespace: $ns, name: row})",
        ns=namespace,
        rows=projection.industries,
    )
    tx.run(
        "UNWIND $rows AS row CREATE (:FundManager {namespace: $ns, name: row})",
        ns=namespace,
        rows=projection.fund_managers,
    )

    tx.run(
        "UNWIND $rows AS row "
        "MATCH (c:Customer {namespace: $ns, customer_id: row.customer_id}) "
        "MATCH (p:Product {namespace: $ns, product_code: row.product_code}) "
        "CREATE (c)-[:HOLDS {namespace: $ns, shares: row.shares, market_value: row.market_value}]->(p)",
        ns=namespace,
        rows=projection.holdings,
    )
    tx.run(
        "UNWIND $rows AS row "
        "MATCH (c:Customer {namespace: $ns, customer_id: row.customer_id}) "
        "MATCH (r:RiskLevel {namespace: $ns, tier: row.tier}) "
        "CREATE (c)-[:HAS_RISK_LEVEL {namespace: $ns}]->(r)",
        ns=namespace,
        rows=projection.customer_risk_levels,
    )
    tx.run(
        "UNWIND $rows AS row "
        "MATCH (p:Product {namespace: $ns, product_code: row.product_code}) "
        "MATCH (i:Industry {namespace: $ns, name: row.industry}) "
        "CREATE (p)-[:BELONGS_TO_INDUSTRY {namespace: $ns, weight: row.weight}]->(i)",
        ns=namespace,
        rows=projection.product_industries,
    )
    tx.run(
        "UNWIND $rows AS row "
        "MATCH (p:Product {namespace: $ns, product_code: row.product_code}) "
        "MATCH (m:FundManager {namespace: $ns, name: row.fund_manager}) "
        "CREATE (p)-[:MANAGED_BY {namespace: $ns}]->(m)",
        ns=namespace,
        rows=projection.product_fund_managers,
    )
    tx.run(
        "UNWIND $rows AS row "
        "MATCH (p:Product {namespace: $ns, product_code: row.product_code}) "
        "MATCH (r:RiskLevel {namespace: $ns, tier: row.tier}) "
        "CREATE (p)-[:SUITABLE_FOR {namespace: $ns}]->(r)",
        ns=namespace,
        rows=projection.product_suitability,
    )

    return GraphStats(
        node_count=(
            len(projection.customers)
            + len(projection.products)
            + len(_RISK_LEVEL_ROWS)
            + len(projection.industries)
            + len(projection.fund_managers)
        ),
        relationship_count=(
            len(projection.holdings)
            + len(projection.customer_risk_levels)
            + len(projection.product_industries)
            + len(projection.product_fund_managers)
            + len(projection.product_suitability)
        ),
    )


def _ensure_indexes(driver: Driver) -> None:
    for statement in _INDEX_STATEMENTS:
        driver.execute_query(statement)


def rebuild_graph(db: Session, driver: Driver, *, namespace: str) -> GraphStats:
    _ensure_indexes(driver)
    projection = _load_projection(db)
    with driver.session() as session:
        return session.execute_write(_apply_rebuild, namespace, projection)
