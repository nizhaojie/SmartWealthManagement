"""持仓穿透：沿产品的底层持有关系逐层展开到底层资产。

展开由 MySQL 递归 CTE 一次完成（ADR-0002），不在应用层写循环拉取。
CTE 带深度上限，并在展开时记录走过的产品以识别成环——两者一起保证查询有界终止；
成环与超限都是报出异常，不是静默截断。

树上的每个节点都带 share（占这笔持仓市值的比例）与 market_value（实际分到的市值），
两者相乘关系在所有层级上一致，因此客户可以横向比较「这只基金实际吃了多少钱」。
"""

from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.customer_assets.service import CENTS, HELD_STATUS, ZERO
from app.exceptions import AppError

MAX_DEPTH = 6

CYCLE_CODE = 1003
DEPTH_CODE = 1004
CYCLE_MESSAGE = "持仓穿透发现成环的底层持有关系"
DEPTH_MESSAGE = "持仓穿透超过深度上限"
HOLDING_NOT_FOUND_MESSAGE = "持仓不存在"

SHARE_PLACES = Decimal("0.000001")
_TRAIL_SEPARATOR = " > "

# 锚点是客户直接持有的产品（第 1 层）；递归步沿 child_product_id 走到下一层产品。
# visited 记录路径上已走过的产品，repeats 为 1 表示这一步走回到了路径上的某个产品。
_RECURSIVE_CTE = """
WITH RECURSIVE look_through AS (
    SELECT
        h.id                                       AS holding_id,
        p.id                                       AS product_id,
        p.product_code                             AS product_code,
        p.product_name                             AS product_name,
        1                                          AS depth,
        CAST(1 AS DECIMAL(24, 12))                 AS weight,
        CAST(CONCAT(',', p.id, ',') AS CHAR(1024)) AS visited,
        0                                          AS repeats,
        CAST(p.product_code AS CHAR(1024))         AS trail
    FROM fin_holdings h
    JOIN fin_product p ON p.id = h.product_id
    WHERE h.customer_id = :customer_id
      AND h.status = :status
      AND p.product_code = :product_code
  UNION ALL
    SELECT
        lt.holding_id,
        child.id,
        child.product_code,
        child.product_name,
        lt.depth + 1,
        CAST(lt.weight * rel.weight AS DECIMAL(24, 12)),
        CAST(CONCAT(lt.visited, child.id, ',') AS CHAR(1024)),
        FIND_IN_SET(CAST(child.id AS CHAR), TRIM(BOTH ',' FROM lt.visited)) > 0,
        CAST(CONCAT(lt.trail, ' > ', child.product_code) AS CHAR(1024))
    FROM look_through lt
    JOIN fin_product_underlying rel ON rel.product_id = lt.product_id
    JOIN fin_product child ON child.id = rel.child_product_id
    WHERE lt.depth < :max_depth
      AND lt.repeats = 0
)
"""

_PRODUCT_STATEMENT = _RECURSIVE_CTE + """
SELECT
    lt.product_code          AS product_code,
    lt.product_name          AS product_name,
    lt.depth                 AS depth,
    lt.weight                AS share,
    lt.repeats               AS repeats,
    lt.trail                 AS trail,
    h.current_value          AS market_value,
    EXISTS (
        SELECT 1 FROM fin_product_underlying nested
        WHERE nested.product_id = lt.product_id AND nested.child_product_id IS NOT NULL
    )                        AS has_nested_product
FROM look_through lt
JOIN fin_holdings h ON h.id = lt.holding_id
ORDER BY lt.depth ASC, lt.weight DESC, lt.product_code ASC
"""

_ASSET_STATEMENT = _RECURSIVE_CTE + """
SELECT
    lt.trail             AS trail,
    lt.weight            AS product_share,
    relation.weight      AS asset_share,
    asset.asset_code     AS asset_code,
    asset.asset_name     AS asset_name,
    asset.asset_category AS asset_category
FROM look_through lt
JOIN fin_product_underlying relation
  ON relation.product_id = lt.product_id AND relation.underlying_asset_id IS NOT NULL
JOIN fin_underlying_asset asset ON asset.id = relation.underlying_asset_id
WHERE lt.repeats = 0
ORDER BY lt.depth ASC, relation.weight DESC, asset.asset_code ASC
"""


def _money(value: Decimal) -> str:
    return format(value.quantize(CENTS), "f")


def _share(value: Decimal) -> str:
    return format(value.quantize(SHARE_PLACES), "f")


def _node(
    *,
    kind: str,
    code: str,
    name: str,
    depth: int,
    share: Decimal,
    market_value: Decimal,
    asset_category: str | None = None,
) -> dict:
    return {
        "kind": kind,
        "code": code,
        "name": name,
        "depth": depth,
        "share": share,
        "market_value": market_value,
        "asset_category": asset_category,
        "children": [],
    }


def _reject_unbounded_expansion(rows: list[dict], *, max_depth: int) -> None:
    cyclic = [row for row in rows if row["repeats"]]
    if cyclic:
        raise AppError(CYCLE_CODE, f"{CYCLE_MESSAGE}：{cyclic[0]['trail']}，展开已停止。")

    truncated = [
        row
        for row in rows
        if row["depth"] == max_depth and row["has_nested_product"] and not row["repeats"]
    ]
    if truncated:
        raise AppError(
            DEPTH_CODE,
            f"{DEPTH_MESSAGE} {max_depth} 层：{truncated[0]['trail']}，更深的层级未展开。",
        )


def _sort_children(node: dict) -> None:
    node["children"].sort(
        key=lambda child: (child["kind"] != "product", -child["market_value"], child["code"])
    )
    for child in node["children"]:
        _sort_children(child)


def _format_tree(node: dict) -> None:
    node["share"] = _share(node["share"])
    node["market_value"] = _money(node["market_value"])
    for child in node["children"]:
        _format_tree(child)


def _build_tree(product_rows: list[dict], asset_rows: list[dict], holding_value: Decimal) -> dict:
    nodes = {
        row["trail"]: _node(
            kind="product",
            code=row["product_code"],
            name=row["product_name"],
            depth=row["depth"],
            share=row["share"],
            market_value=holding_value * row["share"],
        )
        for row in product_rows
        if not row["repeats"]
    }

    for row in product_rows:
        if row["repeats"] or row["depth"] == 1:
            continue
        parent = nodes.get(row["trail"].rsplit(_TRAIL_SEPARATOR, 1)[0])
        child = nodes.get(row["trail"])
        if parent is not None and child is not None:
            parent["children"].append(child)

    for row in asset_rows:
        parent = nodes.get(row["trail"])
        if parent is None:
            continue
        share = row["product_share"] * row["asset_share"]
        parent["children"].append(
            _node(
                kind="asset",
                code=row["asset_code"],
                name=row["asset_name"],
                depth=parent["depth"] + 1,
                share=share,
                market_value=holding_value * share,
                asset_category=row["asset_category"],
            )
        )

    root = next(node for node in nodes.values() if node["depth"] == 1)
    _sort_children(root)
    _format_tree(root)
    return root


def _merge_underlying_assets(asset_rows: list[dict], holding_value: Decimal) -> list[dict]:
    totals: dict[str, dict] = {}
    for row in asset_rows:
        entry = totals.setdefault(
            row["asset_code"],
            {
                "asset_code": row["asset_code"],
                "asset_name": row["asset_name"],
                "asset_category": row["asset_category"],
                "market_value": ZERO,
                "path_count": 0,
            },
        )
        entry["market_value"] += holding_value * row["product_share"] * row["asset_share"]
        entry["path_count"] += 1

    by_size = sorted(
        totals.values(), key=lambda entry: (-entry["market_value"], entry["asset_code"])
    )
    return [
        {
            "asset_code": entry["asset_code"],
            "asset_name": entry["asset_name"],
            "asset_category": entry["asset_category"],
            "market_value": _money(entry["market_value"]),
            "share": _share(entry["market_value"] / holding_value)
            if holding_value
            else _share(ZERO),
            "path_count": entry["path_count"],
        }
        for entry in by_size
    ]


def look_through(
    db: Session,
    *,
    customer_id: int,
    product_code: str,
    max_depth: int = MAX_DEPTH,
) -> dict:
    params = {
        "customer_id": customer_id,
        "status": HELD_STATUS,
        "product_code": product_code,
        "max_depth": max_depth,
    }

    product_rows = [dict(row) for row in db.execute(text(_PRODUCT_STATEMENT), params).mappings()]
    if not product_rows:
        raise AppError(404, HOLDING_NOT_FOUND_MESSAGE)
    _reject_unbounded_expansion(product_rows, max_depth=max_depth)

    asset_rows = [dict(row) for row in db.execute(text(_ASSET_STATEMENT), params).mappings()]
    holding_value = product_rows[0]["market_value"] or ZERO

    return {
        "product_code": product_rows[0]["product_code"],
        "product_name": product_rows[0]["product_name"],
        "market_value": _money(holding_value),
        "root": _build_tree(product_rows, asset_rows, holding_value),
        "underlying_assets": _merge_underlying_assets(asset_rows, holding_value),
    }
