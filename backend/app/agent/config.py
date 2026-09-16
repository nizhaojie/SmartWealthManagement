from dataclasses import dataclass


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
    content_classification_default="事实性内容",
)

DATA_ANALYSIS_CONFIG = AgentConfig(
    name="data_analysis",
    tools=("analytics_query_generation", "analytics_query_execution"),
    content_classification_default="事实性内容",
    # 数据分析不使用知识库检索，retrieval_top_k 保持缺省。
)

ADVISORY_CONFIG = AgentConfig(
    name="advisory",
    tools=("candidate_pool_ranking", "allocation_suggestion"),
    # 调用了推荐类工具即产出投顾内容，因此默认分类是投顾内容，必须经理财顾问审核。
    content_classification_default="投顾内容",
    # 投顾助手不做知识库检索，retrieval_top_k 保持缺省。
)
