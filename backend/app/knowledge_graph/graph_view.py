"""客户关系图的组装：把查询工具的结果拼成前端关系图渲染需要的节点与连线（ticket 04）。

这不是给 Agent 用的查询工具——找答案该用 app.knowledge_graph.tools 里那
六个，这里只管"画出来"需要的形状：客户、产品、行业、基金经理四类节点
（风险等级节点不在可视化范围内，spec 的视觉编码里没有它），默认两跳
（客户→产品→行业），基金经理这一跳按需展开（expand_fund_managers）。

行业节点的集中度标记复用 app.advisory.concentration 的阈值，不在这里
另定一套判断——同一个"超没超"，两处答案不能不一致。
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from decimal import Decimal

from neo4j import Driver, ManagedTransaction
from neo4j.exceptions import DriverError, Neo4jError

from app import degradation
from app.advisory.concentration import CONCENTRATION_THRESHOLD
from app.exceptions import AppError
from app.knowledge_graph import tools
from app.knowledge_graph.schemas import GraphEdge, GraphNode

logger = logging.getLogger("app.knowledge_graph")

# 关系图入口的降级原因：与其余依赖共用同一套统计口径，不另造词。
DEGRADED_TIMEOUT = degradation.REASON_TIMEOUT
DEGRADED_UNAVAILABLE = degradation.REASON_UNAVAILABLE

NODE_TYPE_CUSTOMER = "customer"
NODE_TYPE_PRODUCT = "product"
NODE_TYPE_INDUSTRY = "industry"
NODE_TYPE_FUND_MANAGER = "fund_manager"

EDGE_TYPE_HOLDS = "HOLDS"
EDGE_TYPE_BELONGS_TO_INDUSTRY = "BELONGS_TO_INDUSTRY"
EDGE_TYPE_MANAGED_BY = "MANAGED_BY"


def _customer_node_id(customer_id: int) -> str:
    return f"customer:{customer_id}"


def _product_node_id(product_code: str) -> str:
    return f"product:{product_code}"


def _industry_node_id(name: str) -> str:
    return f"industry:{name}"


def _fund_manager_node_id(name: str) -> str:
    return f"fund_manager:{name}"


def _is_over_threshold(share: float) -> bool:
    return Decimal(str(share)) > CONCENTRATION_THRESHOLD


def _customer_real_name_tx(tx: ManagedTransaction, namespace: str, customer_id: int) -> str | None:
    record = tx.run(
        "MATCH (c:Customer {namespace: $ns, customer_id: $customer_id}) "
        "RETURN c.real_name AS real_name",
        ns=namespace,
        customer_id=customer_id,
    ).single()
    return record["real_name"] if record else None


def _product_fund_managers_tx(
    tx: ManagedTransaction, namespace: str, product_code: str
) -> list[str]:
    result = tx.run(
        "MATCH (:Product {namespace: $ns, product_code: $product_code})"
        "-[:MANAGED_BY]->(m:FundManager {namespace: $ns}) "
        "RETURN m.name AS name ORDER BY m.name",
        ns=namespace,
        product_code=product_code,
    )
    return [record["name"] for record in result]


def customer_graph(
    driver: Driver,
    *,
    namespace: str,
    customer_id: int,
    expand_fund_managers: bool = False,
) -> tuple[list[GraphNode], list[GraphEdge]]:
    holdings = tools.customer_holdings(driver, namespace=namespace, customer_id=customer_id)

    with driver.session() as session:
        real_name = session.execute_read(_customer_real_name_tx, namespace, customer_id)
    if real_name is None:
        return [], []

    nodes: dict[str, GraphNode] = {
        _customer_node_id(customer_id): GraphNode(
            id=_customer_node_id(customer_id),
            type=NODE_TYPE_CUSTOMER,
            label=real_name,
            attrs={"customer_id": customer_id, "real_name": real_name},
        )
    }
    edges: list[GraphEdge] = []

    exposure = tools.customer_industry_exposure(driver, namespace=namespace, customer_id=customer_id)
    share_by_industry = {row.industry: row.share for row in exposure}

    for holding in holdings:
        product_id = _product_node_id(holding.product_code)
        nodes[product_id] = GraphNode(
            id=product_id,
            type=NODE_TYPE_PRODUCT,
            label=holding.product_name,
            attrs={
                "product_code": holding.product_code,
                "product_name": holding.product_name,
                "product_type": holding.product_type,
                "risk_level": holding.risk_level,
                "market_value": holding.market_value,
            },
        )
        edges.append(
            GraphEdge(
                source=_customer_node_id(customer_id), target=product_id, type=EDGE_TYPE_HOLDS
            )
        )

        industries = tools.product_industries(
            driver, namespace=namespace, product_code=holding.product_code
        )
        for industry in industries:
            industry_id = _industry_node_id(industry.industry)
            share = share_by_industry.get(industry.industry, 0.0)
            nodes[industry_id] = GraphNode(
                id=industry_id,
                type=NODE_TYPE_INDUSTRY,
                label=industry.industry,
                attrs={"industry": industry.industry, "share": share},
                marked=_is_over_threshold(share),
            )
            edges.append(
                GraphEdge(
                    source=product_id, target=industry_id, type=EDGE_TYPE_BELONGS_TO_INDUSTRY
                )
            )

        if expand_fund_managers:
            with driver.session() as session:
                fund_managers = session.execute_read(
                    _product_fund_managers_tx, namespace, holding.product_code
                )
            for manager_name in fund_managers:
                manager_id = _fund_manager_node_id(manager_name)
                nodes[manager_id] = GraphNode(
                    id=manager_id,
                    type=NODE_TYPE_FUND_MANAGER,
                    label=manager_name,
                    attrs={"name": manager_name},
                )
                edges.append(
                    GraphEdge(source=product_id, target=manager_id, type=EDGE_TYPE_MANAGED_BY)
                )

    return list(nodes.values()), edges


def customer_graph_degraded(
    driver: Driver,
    *,
    namespace: str,
    customer_id: int,
    expand_fund_managers: bool = False,
    timeout_seconds: float,
) -> tuple[list[GraphNode], list[GraphEdge], str | None]:
    """带降级的关系图查询：返回 (节点, 连线, 降级原因)。

    这是「图谱查询超时跳过增强」在可视化入口上的对应物：图谱是增强，不是依赖，
    查不出来时给一张空图（外加降级标记），而不是让界面收到 500。超时同样用线程池
    做软超时——Neo4j 驱动的阻塞调用没有可靠的协作式取消点。
    """
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        future = executor.submit(
            customer_graph,
            driver,
            namespace=namespace,
            customer_id=customer_id,
            expand_fund_managers=expand_fund_managers,
        )
        nodes, edges = future.result(timeout=timeout_seconds)
    except AppError:
        # 输入本身不合法（如非正数 customer_id）不是依赖抖动：照常拒绝，
        # 不能因为「图谱查不出来就不抛错」把 400 变成一张空图。
        raise
    except FutureTimeoutError:
        logger.warning("关系图降级：图谱查询超时 customer_id=%s", customer_id)
        return [], [], DEGRADED_TIMEOUT
    except (DriverError, Neo4jError):
        logger.warning("关系图降级：Neo4j 不可用 customer_id=%s", customer_id, exc_info=True)
        return [], [], DEGRADED_UNAVAILABLE
    except Exception:  # noqa: BLE001 - 图谱边界：任何失败都退到空图
        logger.exception("关系图降级：图谱查询出现未预期异常 customer_id=%s", customer_id)
        return [], [], DEGRADED_UNAVAILABLE
    finally:
        executor.shutdown(wait=False)
    return nodes, edges, None
