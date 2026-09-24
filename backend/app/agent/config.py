from dataclasses import dataclass

from app.agent.classification import ADVISORY_CONTENT, FACTUAL_CONTENT
from app.db.analytics_account import CUSTOMER_VIEW_NAMES, EMPLOYEE_VIEW_NAMES


@dataclass(frozen=True)
class AgentConfig:
    # ADR-0007：五个 Agent 共用一套 LangGraph 运行时，各自只是这里的一份配置。
    name: str
    tools: tuple[str, ...]
    content_classification_default: str
    retrieval_top_k: int = 5
    # 受限查询可用的语义视图（ADR-0010、ADR-0025）；None 表示目录内的全部视图。
    # 它收在配置里而不是由调用点逐次传入——「这个 Agent 看得到哪些视图」是 Agent
    # 定义的一部分，与工具集、内容分类默认值同类。两域视图互不可见因此也落在这里：
    # 员工侧的 Agent 声明员工侧视图，客户域的那一份声明客户域视图。
    view_names: tuple[str, ...] | None = None


# 智能客服 Agent 的数据查询候选集：客户域四张，加产品要素。产品要素本无行级过滤
# 且是已披露信息，客户拿自己的风险等级筛产品（Cn 筛 R1–Rn）就走它，因此它在客户
# 候选集里而不在「员工侧不可见」的那一边（ADR-0025）。
CUSTOMER_SERVICE_VIEW_NAMES: tuple[str, ...] = CUSTOMER_VIEW_NAMES + ("va_product_element",)

CUSTOMER_SERVICE_CONFIG = AgentConfig(
    name="customer_service",
    tools=("knowledge_search",),
    content_classification_default=FACTUAL_CONTENT,
    # 与员工侧一样显式声明自己那一域：缺省 None 是目录内的全部视图，而
    # 「两域互不可见」是双向的——客服这一侧也不能看见员工侧的客户概况与预警统计。
    view_names=CUSTOMER_SERVICE_VIEW_NAMES,
)

DATA_ANALYSIS_CONFIG = AgentConfig(
    name="data_analysis",
    tools=("analytics_query_generation", "analytics_query_execution"),
    content_classification_default=FACTUAL_CONTENT,
    # 数据分析不使用知识库检索，retrieval_top_k 保持缺省。
    # 候选集显式收在员工侧：语义视图分员工 / 客户两域（ADR-0025），不写死这一行的话
    # 目录里的客户域视图会被一起注入员工侧的提示词——两域就互相看得见了。
    view_names=EMPLOYEE_VIEW_NAMES,
)

ADVISORY_CONFIG = AgentConfig(
    name="advisory",
    tools=("candidate_pool_ranking", "allocation_suggestion"),
    # 调用了推荐类工具即产出投顾内容，因此默认分类是投顾内容，必须经理财顾问审核。
    content_classification_default=ADVISORY_CONTENT,
    # 投顾助手不做知识库检索，retrieval_top_k 保持缺省。
)

# 业务操作 Agent（ADR-0017）：客户经理为名下客户提建议的手段。它与投顾助手是两份
# 配置而不是一份——分工在产物：投顾助手出配置方案，它出「一个产品、一个方向、一个
# 金额、一条理由」的单笔操作建议。工具集也只声明这条产物需要的能力：候选池、客户
# 自己的持仓与资金账户、建议生成；浏览画像、配置比例、收益预测都不在其中。
OPERATION_ADVICE_CONFIG = AgentConfig(
    name="operation_advice",
    tools=(
        "candidate_pool_query",
        "customer_holdings_and_balance_query",
        "operation_advice_generation",
    ),
    # 操作建议是投顾内容（CONTEXT「操作建议」），因此默认分类是投顾内容，必须经
    # 理财顾问放行才能送达客户——由谁发起不改变这条约束。
    content_classification_default=ADVISORY_CONTENT,
    # 业务操作 Agent 与投顾助手都不做知识库检索，retrieval_top_k 保持缺省。
)

# 风控监测 Agent 可查的语义视图：预警统计。它与数据分析 Agent 看的是同一张视图
# 定义（迁移 0008），行级权限也来自同一处，没有风控专用的旁路。
RISK_VIEW_NAMES: tuple[str, ...] = ("va_risk_alert_stat",)

RISK_MONITORING_CONFIG = AgentConfig(
    name="risk_monitoring",
    # 工具集落在风控域内：预警查询、工单操作、规则查询。它们声明这个 Agent 的能力
    # 范围——超出范围的问句在选视图一步就被判为「超出可查范围」，不会落到别的域。
    #
    # 其中只有预警查询走模型：问句复用数据分析 Agent 的语义视图机制（ADR-0010）
    # 转成只读查询，不另开一套链路。工单操作与规则查询由模块既有的具名接口承担，
    # 是人在界面上的显式动作——写操作不经过模型，处置人与理由由登录身份与表单给出。
    tools=("risk_alert_query", "work_order_operation", "risk_rule_query"),
    # 预警是事实记录，查询它们得到的是事实性内容。
    content_classification_default=FACTUAL_CONTENT,
    # 风控 Agent 不做知识库检索，retrieval_top_k 保持缺省。
    view_names=RISK_VIEW_NAMES,
)
