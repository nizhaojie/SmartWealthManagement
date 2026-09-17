"""GraphRAG 的编排：实体识别 → 多跳查询 → 图谱段落；四类情形静默降级
（spec「降级」）。

图谱是增强，不是依赖——这个模块的唯一契约是：不管内部发生什么（Neo4j
连不上、查询超时、一个实体都没识别出来、图谱正在重建且旧图还没建好），
都不能把异常抛给调用方，只能返回一个「降级了、原因是什么」的结果。
降级原因要能被上层写进对话留痕，供事后统计图谱的实际命中率。

超时用线程池给一个软超时：Neo4j 驱动的阻塞调用没有可靠的协作式取消
点，`ThreadPoolExecutor.submit` 之后拿不到结果就直接返回降级、不等
那个线程收尾——底层查询会在自己的驱动超时后自然结束，不必也不能在
这里强行杀掉它。
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass, field
from typing import Any, Literal

from neo4j import Driver
from neo4j.exceptions import DriverError, Neo4jError
from sqlalchemy.orm import Session

from app.exceptions import AppError
from app.knowledge_graph import service as sync_service
from app.knowledge_graph import tools
from app.knowledge_graph.entities import EntityType, ResolvedEntity, extract_entities

logger = logging.getLogger("app")

DEGRADED_TIMEOUT = "graph_query_timeout"
DEGRADED_UNAVAILABLE = "neo4j_unavailable"
DEGRADED_NO_ENTITY = "entity_not_matched"
DEGRADED_REBUILDING = "graph_rebuilding_no_old_graph"

# 属于「外部依赖抖动」的降级原因，应当计入降级留痕。实体未命中不在其中：问题里
# 本来就没有图谱实体是正常结果，把它记成降级会让「系统有多少时间在降级」虚高。
DEPENDENCY_DEGRADATION_REASONS = frozenset(
    {DEGRADED_TIMEOUT, DEGRADED_UNAVAILABLE, DEGRADED_REBUILDING}
)

# 除了 entities.py 里六个真实的实体类型，common_holdings 的段落描述的是
# 一对客户之间的关系，不是单个实体，因此多一个 "customer_pair" 取值。
PassageEntityType = Literal[EntityType, "customer_pair"]


@dataclass
class GraphPassage:
    content: str
    score: float
    entity_type: PassageEntityType
    entity_value: str
    tool: str


@dataclass
class GraphAugmentation:
    passages: list[GraphPassage] = field(default_factory=list)
    matched_entities: list[dict] = field(default_factory=list)
    degraded: bool = False
    degradation_reason: str | None = None


def _passages_for_customer(
    driver: Driver, namespace: str, entity: ResolvedEntity
) -> list[GraphPassage]:
    customer_id = int(entity.identifier)
    passages = []
    for holding in tools.customer_holdings(
        driver, namespace=namespace, customer_id=customer_id
    ):
        passages.append(
            GraphPassage(
                content=(
                    f"{entity.value}持有产品「{holding.product_name}」"
                    f"（{holding.product_type}，风险等级{holding.risk_level}），"
                    f"份额{holding.shares}，市值{holding.market_value}元。"
                ),
                score=1.0,
                entity_type="customer",
                entity_value=entity.value,
                tool="customer_holdings",
            )
        )
    for exposure in tools.customer_industry_exposure(
        driver, namespace=namespace, customer_id=customer_id
    ):
        passages.append(
            GraphPassage(
                content=(
                    f"{entity.value}的持仓中「{exposure.industry}」行业占比约"
                    f"{exposure.share:.0%}，市值合计{exposure.exposure}元。"
                ),
                # 图谱查出的关系是确定的事实，不是相似度意义上的「相关性」——
                # exposure.share/product_industries 的 weight 只描述业务量级
                # 大小，混进置信度分数会让占比小的真实持仓被判定成低置信度，
                # 反而在融合门槛前被误伤。图谱段落统一给满分，量级信息留在
                # 文本内容里供模型和展示使用。
                score=1.0,
                entity_type="customer",
                entity_value=entity.value,
                tool="customer_industry_exposure",
            )
        )
    return passages


def _passages_for_common_holdings(
    driver: Driver, namespace: str, first: ResolvedEntity, second: ResolvedEntity
) -> list[GraphPassage]:
    rows = tools.common_holdings(
        driver,
        namespace=namespace,
        customer_id_a=int(first.identifier),
        customer_id_b=int(second.identifier),
    )
    return [
        GraphPassage(
            content=f"{first.value}与{second.value}共同持有产品「{row.product_name}」（{row.product_type}）。",
            score=1.0,
            entity_type="customer_pair",
            entity_value=f"{first.value}/{second.value}",
            tool="common_holdings",
        )
        for row in rows
    ]


def _passages_from_rows(
    rows: Iterable[Any],
    *,
    entity: ResolvedEntity,
    entity_type: PassageEntityType,
    tool: str,
    format_content: Callable[[Any], str],
) -> list[GraphPassage]:
    return [
        GraphPassage(
            content=format_content(row),
            score=1.0,
            entity_type=entity_type,
            entity_value=entity.value,
            tool=tool,
        )
        for row in rows
    ]


def _passages_for_product(
    driver: Driver, namespace: str, entity: ResolvedEntity
) -> list[GraphPassage]:
    rows = tools.product_industries(driver, namespace=namespace, product_code=str(entity.identifier))
    return _passages_from_rows(
        rows,
        entity=entity,
        entity_type="product",
        tool="product_industries",
        format_content=lambda row: (
            f"产品「{entity.value}」底层资产中「{row.industry}」行业占比约{row.weight:.0%}。"
        ),
    )


def _passages_for_fund_manager(
    driver: Driver, namespace: str, entity: ResolvedEntity
) -> list[GraphPassage]:
    rows = tools.fund_manager_products(
        driver, namespace=namespace, fund_manager=str(entity.identifier)
    )
    return _passages_from_rows(
        rows,
        entity=entity,
        entity_type="fund_manager",
        tool="fund_manager_products",
        format_content=lambda row: (
            f"基金经理「{entity.value}」管理产品「{row.product_name}」"
            f"（{row.product_type}，风险等级{row.risk_level}）。"
        ),
    )


def _passages_for_risk_level(
    driver: Driver, namespace: str, entity: ResolvedEntity
) -> list[GraphPassage]:
    rows = tools.products_for_risk_level(
        driver, namespace=namespace, risk_level=str(entity.identifier)
    )
    return _passages_from_rows(
        rows,
        entity=entity,
        entity_type="risk_level",
        tool="products_for_risk_level",
        format_content=lambda row: (
            f"适合{entity.value}客户的产品：「{row.product_name}」"
            f"（{row.product_type}，产品风险等级{row.risk_level}）。"
        ),
    )


def _run_graph_retrieval(
    driver: Driver, namespace: str, question: str
) -> tuple[list[GraphPassage], list[ResolvedEntity]]:
    with driver.session() as session:
        entities = session.execute_read(extract_entities, namespace, question)

    passages: list[GraphPassage] = []

    customers = [entity for entity in entities if entity.entity_type == "customer"]
    for entity in customers:
        try:
            passages.extend(_passages_for_customer(driver, namespace, entity))
        except AppError:
            continue
    if len(customers) >= 2:
        try:
            passages.extend(
                _passages_for_common_holdings(driver, namespace, customers[0], customers[1])
            )
        except AppError:
            pass

    for entity in entities:
        try:
            if entity.entity_type == "product":
                passages.extend(_passages_for_product(driver, namespace, entity))
            elif entity.entity_type == "fund_manager":
                passages.extend(_passages_for_fund_manager(driver, namespace, entity))
            elif entity.entity_type == "risk_level":
                passages.extend(_passages_for_risk_level(driver, namespace, entity))
        except AppError:
            continue

    return passages, entities


def _graph_unavailable_for_rebuild(db: Session) -> bool:
    status = sync_service.get_status(db)
    return bool(status["running"] and status["synced_at"] is None)


def augment_with_graph(
    driver: Driver,
    db: Session,
    *,
    namespace: str,
    question: str,
    timeout_seconds: float,
) -> GraphAugmentation:
    if _graph_unavailable_for_rebuild(db):
        logger.info("GraphRAG 降级：图谱正在重建且旧图不可用")
        return GraphAugmentation(degraded=True, degradation_reason=DEGRADED_REBUILDING)

    executor = ThreadPoolExecutor(max_workers=1)
    try:
        future = executor.submit(_run_graph_retrieval, driver, namespace, question)
        passages, entities = future.result(timeout=timeout_seconds)
    except FutureTimeoutError:
        logger.warning("GraphRAG 降级：图谱查询超时")
        return GraphAugmentation(degraded=True, degradation_reason=DEGRADED_TIMEOUT)
    except (DriverError, Neo4jError):
        logger.warning("GraphRAG 降级：Neo4j 不可用", exc_info=True)
        return GraphAugmentation(degraded=True, degradation_reason=DEGRADED_UNAVAILABLE)
    except Exception:
        logger.exception("GraphRAG 降级：图谱查询出现未预期异常")
        return GraphAugmentation(degraded=True, degradation_reason=DEGRADED_UNAVAILABLE)
    finally:
        executor.shutdown(wait=False)

    if not entities:
        return GraphAugmentation(degraded=True, degradation_reason=DEGRADED_NO_ENTITY)

    return GraphAugmentation(
        passages=passages,
        matched_entities=[
            {"type": entity.entity_type, "value": entity.value} for entity in entities
        ],
    )
