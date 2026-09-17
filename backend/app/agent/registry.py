"""四个 Agent 的统一注册表：类型 → 配置 → 调用入口。

ADR-0007：四个 Agent 是同一套运行时上的四份配置，路由按登录身份在入口处
确定，不存在运行时的意图分发。这张表是「按 Agent 类型路由」的唯一出处——
某个 Agent 类型叫什么、装配哪份配置、从哪个入口被哪类身份调到，都只在这里
写一遍；`GET /api/agents` 把它读出来，端到端测试据此验证路由。
"""

from dataclasses import dataclass

from app.agent.config import (
    ADVISORY_CONFIG,
    CUSTOMER_SERVICE_CONFIG,
    DATA_ANALYSIS_CONFIG,
    AgentConfig,
    RISK_MONITORING_CONFIG,
)
from app.exceptions import AppError

DOMAIN_CUSTOMER = "customer"
DOMAIN_INTERNAL = "internal"

UNKNOWN_AGENT_MESSAGE = "未知的 Agent 类型"


@dataclass(frozen=True)
class AgentEntry:
    agent_type: str
    config: AgentConfig
    # 这个 Agent 服务哪个身份域（ADR-0004）：客户域只对持牌客户开放，内部域
    # 只对员工开放，一个域签发的凭证在另一个域内无效。
    identity_domain: str
    entry_path: str


AGENT_ENTRIES: tuple[AgentEntry, ...] = (
    AgentEntry(
        agent_type=CUSTOMER_SERVICE_CONFIG.name,
        config=CUSTOMER_SERVICE_CONFIG,
        identity_domain=DOMAIN_CUSTOMER,
        # entry_path 是调用这个 Agent 的那条入口路由，端到端测试据此把请求
        # 打到真实链路上——写前缀的话，路由漂移不会让任何断言失败。
        entry_path="/api/customer/chat/messages",
    ),
    AgentEntry(
        agent_type=DATA_ANALYSIS_CONFIG.name,
        config=DATA_ANALYSIS_CONFIG,
        identity_domain=DOMAIN_INTERNAL,
        entry_path="/api/internal/analytics/query",
    ),
    AgentEntry(
        agent_type=ADVISORY_CONFIG.name,
        config=ADVISORY_CONFIG,
        identity_domain=DOMAIN_INTERNAL,
        # 投顾助手的入口是生成方案这一条；审核与读取是理财顾问工作台的路由，
        # 不是调用 Agent 本身。
        entry_path="/api/internal/advisory/customers/{customer_id}/plan",
    ),
    AgentEntry(
        agent_type=RISK_MONITORING_CONFIG.name,
        config=RISK_MONITORING_CONFIG,
        identity_domain=DOMAIN_INTERNAL,
        entry_path="/api/internal/risk-monitoring/query",
    ),
)

AGENTS: dict[str, AgentEntry] = {entry.agent_type: entry for entry in AGENT_ENTRIES}


def resolve_agent(agent_type: str) -> AgentEntry:
    entry = AGENTS.get(agent_type)
    if entry is None:
        raise AppError(404, UNKNOWN_AGENT_MESSAGE)
    return entry


def serialize_agent(entry: AgentEntry) -> dict:
    return {
        "agent_type": entry.agent_type,
        "tools": list(entry.config.tools),
        "content_classification_default": entry.config.content_classification_default,
        "identity_domain": entry.identity_domain,
        "entry_path": entry.entry_path,
    }
