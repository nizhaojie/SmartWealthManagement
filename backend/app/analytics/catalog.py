"""语义视图目录：每个视图的场景说明、口径与关键词（ADR-0010）。

按问题关键词只注入相关视图的定义，不注入全部——否则提示词随视图增多
而膨胀。视图的列清单不在此处手维护，而是从 information_schema 内省得到，
保证注入的定义与迁移创建的视图不漂移。
"""

from collections.abc import Collection
from dataclasses import dataclass

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.db.analytics_account import ANALYTICS_VIEW_NAMES


@dataclass(frozen=True)
class ViewSpec:
    name: str
    summary: str  # 场景与口径说明，随列清单一并注入提示词
    keywords: tuple[str, ...]


VIEW_CATALOG: tuple[ViewSpec, ...] = (
    ViewSpec(
        name="va_customer_overview",
        summary=(
            "客户概况：一行一个客户。asset_scale 为资产规模，口径固定为"
            "「持有中」持仓的当前市值合计，无持仓为 0；customer_name 已脱敏。"
        ),
        keywords=("客户", "资产规模", "概况", "分层", "开户", "风险承受"),
    ),
    ViewSpec(
        name="va_holding_distribution",
        summary="持仓分布：一行一条持仓，带产品要素，供按产品类型 / 风险等级聚合。",
        keywords=("持仓", "持有", "市值", "盈亏", "份额", "分布", "配置"),
    ),
    ViewSpec(
        name="va_transaction_stat",
        summary="交易统计：一行一笔交易，带产品要素，供按时间 / 类型 / 产品聚合。",
        keywords=("交易", "申购", "赎回", "流水", "成交金额"),
    ),
    ViewSpec(
        name="va_product_element",
        summary="产品要素：产品主数据，不含客户数据，无行级过滤。",
        keywords=("产品要素", "费率", "起投", "期限", "基金经理", "业绩基准", "风险等级"),
    ),
    ViewSpec(
        name="va_risk_alert_stat",
        summary="预警统计：一行一条预警，含类型、等级、状态与触发时间。",
        keywords=("预警", "风控", "告警"),
    ),
)


def select_views(
    question: str, *, allowed: Collection[str] | None = None
) -> list[ViewSpec]:
    """按问题关键词筛出相关视图；一个都匹配不上时返回空（超出可查范围）。

    ``allowed`` 把候选收窄到某个 Agent 的视图范围（如风控监测 Agent 只看得到
    预警统计视图）。它是提示词注入范围的收紧，不是权限边界——行级权限与脱敏
    内建在视图定义里，与这里无关。
    """
    return [
        spec
        for spec in VIEW_CATALOG
        if (allowed is None or spec.name in allowed)
        and any(keyword in question for keyword in spec.keywords)
    ]


def view_definitions(db: Session, views: list[ViewSpec]) -> str:
    """拼出注入提示词的视图定义：场景与口径说明 + 内省得到的列清单。"""
    columns = _introspect_columns(db, [view.name for view in views])
    blocks = []
    for view in views:
        column_text = ", ".join(
            f"{name} {column_type}" for name, column_type in columns[view.name]
        )
        blocks.append(f"视图 {view.name}：{view.summary}\n列：{column_text}")
    return "\n\n".join(blocks)


def _introspect_columns(
    db: Session, view_names: list[str]
) -> dict[str, list[tuple[str, str]]]:
    rows = (
        db.execute(
            text(
                "SELECT table_name, column_name, column_type"
                " FROM information_schema.columns"
                " WHERE table_schema = DATABASE() AND table_name IN :view_names"
                " ORDER BY table_name, ordinal_position"
            ).bindparams(bindparam("view_names", expanding=True)),
            {"view_names": view_names},
        )
        .all()
    )
    columns: dict[str, list[tuple[str, str]]] = {name: [] for name in view_names}
    for table_name, column_name, column_type in rows:
        columns[str(table_name)].append((str(column_name), str(column_type)))
    return columns


def _catalog_covers_the_grant_list() -> bool:
    # 目录与授权清单（即迁移创建的视图集合）必须一致，漂移意味着有的视图
    # 永远注入不进提示词，或目录指向不存在的视图。
    return {spec.name for spec in VIEW_CATALOG} == set(ANALYTICS_VIEW_NAMES)


assert _catalog_covers_the_grant_list(), "VIEW_CATALOG 与 ANALYTICS_VIEW_NAMES 不一致"
