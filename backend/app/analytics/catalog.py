"""语义视图目录：每个视图的场景说明、口径、关键词与中文列标签（ADR-0010、ADR-0025、ADR-0028）。

按问题关键词只注入相关视图的定义，不注入全部——否则提示词随视图增多
而膨胀。视图的列清单不在此处手维护，而是从 information_schema 内省得到，
保证注入的定义与迁移创建的视图不漂移。

目录分两域，与视图本身一样互相独立：员工侧五张（``EMPLOYEE_VIEW_CATALOG``）、
客户域四张（``CUSTOMER_VIEW_CATALOG``）。Agent 的候选集由 ``select_views`` 的
``allowed`` 收窄——每个 Agent 在自己的配置里声明看得到哪一域
（``app.agent.config.AgentConfig.view_names``），两域因此互不可见。
"""

from collections.abc import Collection, Mapping
from dataclasses import dataclass, field

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.db.analytics_account import ANALYTICS_VIEW_NAMES


@dataclass(frozen=True)
class ViewSpec:
    name: str
    summary: str  # 场景与口径说明，随列清单一并注入提示词
    keywords: tuple[str, ...]
    # 可查项的人话名称：客户问到白名单之外时，把它列出来告诉客户「能查什么」
    # （ADR-0025）。留空的视图不进那张清单——员工侧视图不进客户候选集，也就
    # 没有对客户报菜名的场合。
    label: str = ""
    # 列的中文表头：客户侧的结果表用它（ADR-0028），键是视图里的列名。没写标签的
    # 列在运行时回落列名——宁可表头出现英文 snake_case，也不悄悄吞掉一列数据；
    # 「列面 == 标签键集合」由集成测试盯着（`test_semantic_views.py`），迁移加了列
    # 而这里没补标签时红在 CI 里，而不是红在客户眼前。
    column_labels: Mapping[str, str] = field(default_factory=dict)


# 员工侧：行级范围由角色与归属关系决定，敏感字段已脱敏（迁移 0008）。
EMPLOYEE_VIEW_CATALOG: tuple[ViewSpec, ...] = (
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
        label="产品要素",
        # 它是两域共有的那一张视图，因此也在客户候选集里：客户问「有什么适合我的
        # 风险等级的产品」拿到的清单就是它，表头同样是客户看得见的东西。
        column_labels={
            "product_code": "产品代码",
            "product_name": "产品名称",
            "product_type": "产品类型",
            # 产品自身的分级叫「产品风险等级」；「风险等级」是 CONTEXT.md 里的 Avoid
            # 写法（它会被读成客户那一档），客户侧表头因此不省这个前缀。
            "risk_level": "产品风险等级",
            "expected_return": "预期年化收益率",
            "min_amount": "起投金额",
            "term_days": "期限天数",
            "fee_rate": "费率",
            "fund_manager": "基金经理",
            "product_status": "产品状态",
        },
    ),
    ViewSpec(
        name="va_risk_alert_stat",
        summary="预警统计：一行一条预警，含类型、等级、状态与触发时间。",
        keywords=("预警", "风控", "告警"),
    ),
)

# 客户域：行级范围锁死为凭证客户本人，未设置身份返回零行；本人数据不脱敏。
# 关键词按客户口语选取（「这个月充了多少」里的「充」也得命中），因为它们直接
# 决定一个问题有没有候选视图——一个都匹配不上就是「超出可查范围」。
CUSTOMER_VIEW_CATALOG: tuple[ViewSpec, ...] = (
    ViewSpec(
        name="va_my_holdings",
        # 客户域四张视图的口径说明会原样进客户可见的 `answer`（`_basis_text`），
        # 因此不写英文列名——列名只以 `columns[].key` 存在，不上界面（ADR-0028）。
        # 字段含义用中文标签表达，模型侧另有内省得到的列清单一并注入。
        summary=(
            "我的持仓明细：一行一条持仓，口径与资产页一致——只含「持有中」的持仓；"
            "「当前市值」按最新净值计，「成本金额」为买入成本，本人数据不脱敏。"
        ),
        keywords=("持仓", "持有", "我的产品", "买了什么", "市值", "盈亏", "份额"),
        label="持仓明细",
        column_labels={
            "customer_id": "客户编号",
            "product_code": "产品代码",
            "product_name": "产品名称",
            "product_type": "产品类型",
            "product_risk_level": "产品风险等级",
            "shares": "持有份额",
            "cost_amount": "成本金额",
            "market_value": "当前市值",
            "profit_loss": "盈亏金额",
            "profit_ratio": "盈亏比例",
        },
    ),
    ViewSpec(
        name="va_my_transactions",
        summary=(
            "我的交易流水：一行一笔资金操作，申购 / 赎回 / 转账 / 充值共用同一个形状"
            "（「产品代码」与「产品名称」只有申赎有，「收款人」与「收款账号」只有转账有，"
            "「状态」恒为「已确认」）。"
        ),
        # 「转」单字也在关键词里：客户的口语是「这个月转了多少」，不是「转账」；
        # 关键词只决定注入哪些视图定义，不构成权限边界。
        keywords=(
            "交易",
            "流水",
            "充值",
            "充",
            "入金",
            "转",
            "转账",
            "申购",
            "赎回",
            "扣款",
        ),
        label="交易流水",
        column_labels={
            "customer_id": "客户编号",
            "transaction_no": "交易编号",
            "transaction_type": "交易类型",
            "product_code": "产品代码",
            "product_name": "产品名称",
            "amount": "金额",
            "shares": "份额",
            "nav": "单位净值",
            "fee": "手续费",
            "status": "状态",
            "traded_at": "交易时间",
            "payee_name": "收款人",
            "payee_account": "收款账号",
        },
    ),
    ViewSpec(
        name="va_my_funding_account",
        summary=(
            "我的资金账户：一行一位客户，「可用余额」的口径与资金页一致——它不含"
            "持仓市值，也不是画像里的总资产。"
        ),
        keywords=("余额", "资金账户", "可用余额", "账户余额", "多少钱"),
        label="资金账户余额",
        column_labels={
            "customer_id": "客户编号",
            "available_balance": "可用余额",
        },
    ),
    ViewSpec(
        name="va_my_risk_assessment",
        summary=(
            "我的风险承受等级结论：一行一位客户，只含当前结论——「风险承受等级」取"
            " C1 到 C5，「有效期至」为结论的有效期。"
        ),
        keywords=("风险等级", "风险承受", "风评", "测评", "风险测评"),
        label="风险承受等级",
        column_labels={
            "customer_id": "客户编号",
            # 本人那一档叫「风险承受等级」，不是「风险等级」（CONTEXT.md 的 Avoid）。
            "risk_level": "风险承受等级",
            "valid_until": "有效期至",
        },
    ),
)

# 全部语义视图（两域合并）。它与授权清单必须一致；各 Agent 的候选集另由
# ``select_views(allowed=...)`` 收窄到自己的那一域。
VIEW_CATALOG: tuple[ViewSpec, ...] = EMPLOYEE_VIEW_CATALOG + CUSTOMER_VIEW_CATALOG


def select_views(
    question: str, *, allowed: Collection[str] | None = None
) -> list[ViewSpec]:
    """按问题关键词筛出相关视图；一个都匹配不上时返回空（超出可查范围）。

    ``allowed`` 把候选收窄到某个 Agent 的视图范围（如风控监测 Agent 只看得到
    预警统计视图、智能客服看得到客户域视图）。它是提示词注入范围的收紧，不是权限
    边界——行级权限与脱敏内建在视图定义里，与这里无关。缺省是目录内的全部视图；
    两域互不可见靠各 Agent 显式传入自己那一域来保证（``AgentConfig.view_names``）。
    """
    return [
        spec
        for spec in VIEW_CATALOG
        if (allowed is None or spec.name in allowed)
        and any(keyword in question for keyword in spec.keywords)
    ]


def queryable_topics(view_names: Collection[str]) -> list[str]:
    """给定视图范围里的「可查项」名称，顺序跟随传入的视图名。

    客户问到候选集之外时，话术要把可查的东西列出来（ADR-0025）——那张清单由这里
    从目录生成，而不是在手写话术里再抄一遍白名单：抄一遍，改白名单时话术就会撒谎。
    """
    specs = {spec.name: spec for spec in VIEW_CATALOG}
    return [
        specs[name].label
        for name in view_names
        if name in specs and specs[name].label
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
