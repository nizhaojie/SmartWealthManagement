"""从问题文本里识别能对应到图中真实节点的实体（spec「实体识别」）。

用图谱自身的节点属性做 gazetteer 匹配，而不是接入一套独立的 NER 模型——
这样「识别出的实体要能对应到图中真实节点」是天然成立的：匹配的来源
就是图节点本身，不存在两边对不上、需要额外校验的情况。风险等级是
唯一的例外，C1..C5 是一个五个值的封闭词表，直接用正则识别，不必为
它查一遍图谱。

识别不到任何实体不是错误——调用方（app.knowledge_graph.graphrag）把
空列表当成四类静默降级情形之一处理，这里只管识别，不管降级策略。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from neo4j import ManagedTransaction

EntityType = Literal["customer", "product", "fund_manager", "industry", "risk_level"]

_RISK_LEVEL_PATTERN = re.compile(r"C[1-5]")


@dataclass(frozen=True)
class ResolvedEntity:
    """一个识别出的实体。

    `identifier` 是喂给 app.knowledge_graph.tools 里查询工具的实体标识
    （customer_id 是 int，其余是 str），`value` 是原文里对应的名称/代码，
    用于拼装注入模型的文本与展示。industry 没有对应的查询工具（六个
    工具里没有「按行业反查产品」），identifier 与 value 相同，仅用于
    留痕，不会驱动任何查询。
    """

    entity_type: EntityType
    value: str
    identifier: int | str


def _load_gazetteer(tx: ManagedTransaction, namespace: str) -> dict[str, list]:
    customers = [
        dict(record)
        for record in tx.run(
            "MATCH (c:Customer {namespace: $ns}) "
            "RETURN c.customer_id AS customer_id, c.real_name AS real_name",
            ns=namespace,
        )
    ]
    products = [
        dict(record)
        for record in tx.run(
            "MATCH (p:Product {namespace: $ns}) "
            "RETURN p.product_code AS product_code, p.product_name AS product_name",
            ns=namespace,
        )
    ]
    fund_managers = [
        record["name"]
        for record in tx.run(
            "MATCH (m:FundManager {namespace: $ns}) RETURN m.name AS name", ns=namespace
        )
    ]
    industries = [
        record["name"]
        for record in tx.run(
            "MATCH (i:Industry {namespace: $ns}) RETURN i.name AS name", ns=namespace
        )
    ]
    return {
        "customers": customers,
        "products": products,
        "fund_managers": fund_managers,
        "industries": industries,
    }


def _dedupe(entities: list[ResolvedEntity]) -> list[ResolvedEntity]:
    seen: set[tuple[str, int | str]] = set()
    deduped: list[ResolvedEntity] = []
    for entity in entities:
        key = (entity.entity_type, entity.identifier)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(entity)
    return deduped


def extract_entities(
    tx: ManagedTransaction, namespace: str, question: str
) -> list[ResolvedEntity]:
    """事务函数：签名与 app.knowledge_graph.tools 里的查询函数一致，配 session.execute_read 使用。"""
    gazetteer = _load_gazetteer(tx, namespace)
    resolved: list[ResolvedEntity] = []

    for row in gazetteer["customers"]:
        name = row["real_name"]
        if name and name in question:
            resolved.append(ResolvedEntity("customer", name, row["customer_id"]))

    for row in gazetteer["products"]:
        name = row["product_name"]
        if name and name in question:
            resolved.append(ResolvedEntity("product", name, row["product_code"]))

    for name in gazetteer["fund_managers"]:
        if name and name in question:
            resolved.append(ResolvedEntity("fund_manager", name, name))

    for name in gazetteer["industries"]:
        if name and name in question:
            resolved.append(ResolvedEntity("industry", name, name))

    for match in _RISK_LEVEL_PATTERN.finditer(question):
        code = match.group()
        resolved.append(ResolvedEntity("risk_level", code, code))

    return _dedupe(resolved)
