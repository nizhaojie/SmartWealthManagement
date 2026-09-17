"""风控专员自然语言查询的 Agent 装配（ADR-0007 / ADR-0010）。

问「今天有哪些高风险预警」不必自己拼筛选条件：问题交给风控监测 Agent 的
查询链路，转成一条作用于**预警统计语义视图**的只读查询，再由模型把结构化
结果讲回自然语言。

两处刻意的边界：

- **复用数据分析 Agent 的查询链路与语义视图机制**（``analytics.service.run_query``
  + ``va_risk_alert_stat``），不另开一套。视图范围收窄到风控域，超出范围的
  问题在选视图一步就没有候选，直接判为「超出可查范围」。
- **阈值判断不经过模型**。模型这一侧只做两件事：把问句转成查询、把结果讲成
  话。交易是否异常早在规则引擎求值时就已经确定（``app.risk_monitoring``），
  这里查的是已经产生的预警事实，模型不改写、也不产生任何预警。

放在 ``app.agent`` 而不是 ``app.risk_monitoring``：那是确定性求值的核心包，
有一条护栏测试禁止它引入模型层（``test_evaluation_path_never_imports_the_model_layer``）。
自然语言查询是 Agent 侧的事，与规则求值分属两层。
"""

from __future__ import annotations

import redis
from sqlalchemy.orm import Session

from app.agent.config import RISK_MONITORING_CONFIG
from app.analytics.schemas import AnalyticsQueryResponse
from app.analytics.service import run_query
from app.db.models import Employee
from app.settings import Settings

# 风控监测 Agent 可查的语义视图：预警统计。它与数据分析 Agent 看的是同一张
# 视图定义（迁移 0008），行级权限也来自同一处，没有风控专用的旁路。
RISK_VIEW_NAMES: tuple[str, ...] = ("va_risk_alert_stat",)

# 记忆命名空间：风控问答的多轮上下文与数据分析的互不串味。
RISK_MEMORY_NAMESPACE = "risk_query"


def run_risk_query(
    db: Session,
    settings: Settings,
    *,
    employee: Employee,
    question: str,
    cache: redis.Redis | None = None,
    session_id: str | None = None,
) -> AnalyticsQueryResponse:
    """把风控专员的问句转成对预警数据的查询并返回结果。

    ``session_id`` 存在时，上一轮问题进入生成上下文——「那今天呢」这类不含
    关键词的追问才成立（``app.analytics.service``）。
    """
    return run_query(
        db,
        settings,
        employee=employee,
        question=question,
        cache=cache,
        session_id=session_id,
        config=RISK_MONITORING_CONFIG,
        view_names=RISK_VIEW_NAMES,
        memory_namespace=RISK_MEMORY_NAMESPACE,
    )
