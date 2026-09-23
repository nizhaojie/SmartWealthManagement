"""风险关注：一个 Agent 注意到某位客户有风险，留给其他 Agent 的提示记录。

它既不是预警——预警是风控规则命中的事实记录，由规则引擎产生；也不是工单——工单是
处置流程的载体。风险关注记录回答的是「谁在什么时候因为什么提醒了谁」：

- 风控发出预警 → 投顾助手为这位客户生成方案时带上风险标记（`app.advisory.warnings`）；
- 客服察觉到高风险意图 → 风控专员在风险关注列表里看到这位客户。

记录只追加，不改写，也没有「已处理」状态：它是一次观察的留痕。发布方不知道有谁在听，
每条订阅各自写下自己要的那一份，因此这条链路坏了也只是少一条提示，不影响任何一个
核心流程。

**广播是通知，不是数据通道，所以这里不存原始事件载荷。** 记录只留下读取方（投顾的
风险标记、风控专员列表）真正要看的那几样：谁提醒的、提醒什么、什么时候、什么等级。
广播漏了就少一条关注，需要完整追溯时回到权威来源——预警在 `fin_risk_alert`，对话原文
在会话归档——而不是让这里承担第二份真相（spec 的 Out of Scope 也明确不做事件的持久化
与重放）。
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.customer_scope import restrict_to_own_customers
from app.db.models import Customer, Employee, RiskFocus
from app.pagination import PageParams, count_matching, paginated_response

FOCUS_RISK_ALERT = "风控预警"
FOCUS_RISK_INTENT = "高风险意图"

FOCUS_TYPES: tuple[str, ...] = (FOCUS_RISK_ALERT, FOCUS_RISK_INTENT)


def alert_reason(payload: Mapping[str, Any]) -> str:
    """预警事件 → 一句可读的关注理由，带等级与命中规则。"""
    level = str(payload.get("alert_level") or "未分级")
    codes = "、".join(str(code) for code in payload.get("rule_codes") or [])
    detail = f"命中规则 {codes}" if codes else "无规则明细"
    return f"风控预警（{level}）：{detail}"


def intent_reason(payload: Mapping[str, Any]) -> str:
    """高风险意图事件 → 一句可读的关注理由。"""
    what = payload.get("reason") or payload.get("intent_code") or "未说明"
    return f"客服识别到高风险意图：{what}"


def record(
    db: Session,
    *,
    customer_id: int,
    focus_type: str,
    reason: str,
    source: str,
    occurred_at: datetime,
    trace_id: str = "",
    severity: str | None = None,
) -> RiskFocus:
    """落一条关注记录。订阅方写完就返回，不回头通知发布方。"""
    focus = RiskFocus(
        customer_id=customer_id,
        focus_type=focus_type,
        severity=severity,
        reason=reason,
        source=source,
        trace_id=trace_id,
        occurred_at=occurred_at,
    )
    db.add(focus)
    db.commit()
    db.refresh(focus)
    return focus


def recent_for_customer(
    db: Session, *, customer_id: int, focus_type: str, since: datetime
) -> list[RiskFocus]:
    """某位客户在时间窗内的关注记录，最近的在前。

    时间基准由调用方显式传入（ADR-0011）：窗口要能被测试固定住，不能读运行时当前时间。
    """
    return list(
        db.scalars(
            select(RiskFocus)
            .where(
                RiskFocus.customer_id == customer_id,
                RiskFocus.focus_type == focus_type,
                RiskFocus.occurred_at >= since,
            )
            .order_by(RiskFocus.occurred_at.desc(), RiskFocus.id.desc())
        ).all()
    )


def focus_facts(focus: RiskFocus) -> dict:
    """一条关注记录自身的事实。客户名之类的上下文由读取方按需补。"""
    return {
        "id": focus.id,
        "customer_id": focus.customer_id,
        "focus_type": focus.focus_type,
        "severity": focus.severity,
        "reason": focus.reason,
        "source": focus.source,
        "trace_id": focus.trace_id,
        "occurred_at": focus.occurred_at,
    }


def list_recent(
    db: Session, *, employee: Employee, page: PageParams, focus_type: str | None = None
) -> dict:
    """风险关注列表的一页，最近的在前。

    可见范围与预警、工单同一口径：客户经理只看得到自己名下客户的记录，其他内部
    角色不受限（`app.customer_scope`）。

    排序键是 `occurred_at` 倒序 + `id` 兜底：时间只有秒精度，同一秒落下的多条记录
    若不分先后，翻页时会在两页之间来回跳——顺序不稳定，页数就切不准。
    """
    conditions = []
    if restrict_to_own_customers(employee):
        conditions.append(Customer.manager_id == employee.id)
    if focus_type is not None:
        conditions.append(RiskFocus.focus_type == focus_type)

    # `total` 由这条查询派生（`count_matching`），条件只写一遍：各写一遍必然漂移。
    base = (
        select(RiskFocus, Customer.real_name)
        .join(Customer, Customer.id == RiskFocus.customer_id)
        .where(*conditions)
    )
    total = count_matching(db, base)
    rows = db.execute(
        base.order_by(RiskFocus.occurred_at.desc(), RiskFocus.id.desc())
        .offset(page.offset)
        .limit(page.page_size)
    ).all()
    items = [
        {**focus_facts(focus), "occurred_at": focus.occurred_at.isoformat(), "customer_name": name}
        for focus, name in rows
    ]
    return paginated_response(items, total=total, params=page)
