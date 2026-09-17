from dataclasses import dataclass

from app.agent.classification import ADVISORY_CONTENT, FACTUAL_CONTENT


@dataclass(frozen=True)
class AgentConfig:
    # ADR-0007：四个 Agent 共用一套 LangGraph 运行时，各自只是这里的一份配置。
    name: str
    tools: tuple[str, ...]
    content_classification_default: str
    retrieval_top_k: int = 5


CUSTOMER_SERVICE_CONFIG = AgentConfig(
    name="customer_service",
    tools=("knowledge_search",),
    content_classification_default=FACTUAL_CONTENT,
)

DATA_ANALYSIS_CONFIG = AgentConfig(
    name="data_analysis",
    tools=("analytics_query_generation", "analytics_query_execution"),
    content_classification_default=FACTUAL_CONTENT,
    # 数据分析不使用知识库检索，retrieval_top_k 保持缺省。
)

ADVISORY_CONFIG = AgentConfig(
    name="advisory",
    tools=("candidate_pool_ranking", "allocation_suggestion"),
    # 调用了推荐类工具即产出投顾内容，因此默认分类是投顾内容，必须经理财顾问审核。
    content_classification_default=ADVISORY_CONTENT,
    # 投顾助手不做知识库检索，retrieval_top_k 保持缺省。
)

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
)
