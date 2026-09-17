"""Agent 注册表的只读出口。

系统的统一入口是 `app.agent.registry`：按 Agent 类型列出四个 Agent 的配置、
身份域与调用入口。它只是静态的路由事实，不含任何客户数据，因此无需认证。
"""

from fastapi import APIRouter

from app.agent.registry import AGENT_ENTRIES, serialize_agent
from app.http import ok

router = APIRouter(prefix="/api/agents")


@router.get("")
def list_agents():
    return ok([serialize_agent(entry) for entry in AGENT_ENTRIES])
