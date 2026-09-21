"""预警的读取：列表与详情。

都是只读，但可见范围要收紧：**客户经理只看得到自己名下客户的预警**，其他内部角色
不受限——与工单列表、审核内容的查看是同一口径，规则写在 `app.customer_scope`。

详情把风控专员判断误报需要的事实一次给全：命中依据（到字段与值的粒度）、关联交易、
客户信息、这位客户的历史预警，以及这条预警有没有派生工单。它们收在一个响应里，是
因为「判断一条预警」要求这些事实同时在场——每切换一次页面就丢一次上下文。

写操作不在这里：预警自身的排除与升级在 `app.risk_monitoring.disposition`，派生工单
之后的处置在 `app.work_order.service`。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.customer_scope import is_under_management, restrict_to_own_customers
from app.db.models import (
    Customer,
    CustomerProfile,
    Employee,
    Product,
    RiskAlert,
    Transaction,
    WorkOrder,
)
from app.employees import names_by_id
from app.exceptions import AppError
from app.risk_monitoring import alerting, disposition
from app.work_order import service as work_orders

# 历史预警只取最近这些条：判断「偶发还是模式」看的是近期行为，而把一位客户的
# 全部预警铺在详情页上会把当前这条淹掉。
HISTORY_LIMIT = 20

NOT_YOUR_CUSTOMER_MESSAGE = "该预警不在你名下客户的范围内，无权查看"
CUSTOMER_NOT_FOUND_MESSAGE = "客户不存在"


def _work_orders_by_alert(db: Session, alert_ids: set[int]) -> dict[int, WorkOrder]:
    """这批预警各自派生的工单。

    一次查完而不是逐条查：列表页每行都要显示「有没有工单」，按行查就是 N 次往返。
    """
    if not alert_ids:
        return {}
    rows = db.scalars(
        select(WorkOrder).where(WorkOrder.source_alert_id.in_(alert_ids))
    ).all()
    return {row.source_alert_id: row for row in rows if row.source_alert_id is not None}


def _summary(
    alert: RiskAlert,
    *,
    customer_name: str,
    work_order: WorkOrder | None,
    source: str,
) -> dict:
    """列表行的字段：预警自身的事实，加上「谁的」「谁发起的」与「有没有工单」。

    足够排序、筛选与决定「接下来看哪一条」，但不含命中依据——那是详情页的事，
    列表上每一行都带一份依据会让这个响应长得没有道理。
    """
    return {
        **alerting.alert_core(alert),
        "customer_name": customer_name,
        # 来源要在一眼扫过时就能看到：风控专员靠它决定这条值不值得信（客户发起 vs
        # 绕过业务校验的内部补录）。
        "source": source,
        "rule_count": len(alert.rule_codes or []),
        "work_order_id": work_order.id if work_order is not None else None,
        "work_order_status": work_order.status if work_order is not None else None,
    }


def list_alerts(
    db: Session,
    *,
    employee: Employee,
    alert_level: str | None = None,
    status: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
) -> list[dict]:
    """预警列表，按产生时间倒序。

    筛选条件都是可选的事实字段：等级、状态、时间范围。默认顺序是「最新的在最前面」
    ——预警是越新越需要看的东西；置信度排序由调用方在本地做，那是同一批数据的另一种
    排列，不必再往返一次。
    """
    query = select(RiskAlert, Customer.real_name).join(
        Customer, Customer.id == RiskAlert.customer_id
    )
    if restrict_to_own_customers(employee):
        query = query.where(Customer.manager_id == employee.id)
    if alert_level is not None:
        query = query.where(RiskAlert.alert_level == alert_level)
    if status is not None:
        query = query.where(RiskAlert.status == status)
    if created_from is not None:
        query = query.where(RiskAlert.create_time >= created_from)
    if created_to is not None:
        query = query.where(RiskAlert.create_time <= created_to)

    rows = db.execute(query.order_by(RiskAlert.create_time.desc(), RiskAlert.id.desc())).all()
    alerts = [alert for alert, _name in rows]
    orders = _work_orders_by_alert(db, {alert.id for alert in alerts})
    sources = alerting.alert_sources(db, alerts)
    return [
        _summary(
            alert,
            customer_name=name,
            work_order=orders.get(alert.id),
            source=sources[alert.id],
        )
        for alert, name in rows
    ]


def _transactions(db: Session, transaction_ids: list[int]) -> list[dict]:
    """预警关联的交易，连产品名称一起给。

    产品代码与名称在这一层拼上：详情页要说明「这五十万买的是什么」，让调用方拿着
    product_id 再查一次才是把上下文又丢回给界面。
    """
    if not transaction_ids:
        return []
    rows = db.execute(
        select(Transaction, Product.product_code, Product.product_name)
        .join(Product, Product.id == Transaction.product_id, isouter=True)
        .where(Transaction.id.in_(transaction_ids))
        .order_by(Transaction.create_time.asc(), Transaction.id.asc())
    ).all()
    return [
        {
            "id": transaction.id,
            "transaction_no": transaction.transaction_no,
            "customer_id": transaction.customer_id,
            "product_id": transaction.product_id,
            "product_code": product_code or "",
            "product_name": product_name or "",
            "transaction_type": transaction.transaction_type,
            "amount": format(transaction.amount, "f"),
            "shares": format(transaction.shares, "f"),
            "nav": format(transaction.nav, "f"),
            "fee": format(transaction.fee, "f"),
            "status": transaction.status,
            "occurred_at": transaction.create_time.isoformat(),
        }
        for transaction, product_code, product_name in rows
    ]


def _customer_history(db: Session, *, customer_id: int, exclude_alert_id: int) -> list[dict]:
    """这位客户除本条之外的预警，最近的在前。

    排除本条的用意是让「历史」真的是历史：风控专员要看的是「以前还发生过什么」，
    把当前这条混进去只会占掉一行。
    """
    rows = db.scalars(
        select(RiskAlert)
        .where(RiskAlert.customer_id == customer_id, RiskAlert.id != exclude_alert_id)
        .order_by(RiskAlert.create_time.desc(), RiskAlert.id.desc())
        .limit(HISTORY_LIMIT)
    ).all()
    return [alerting.alert_core(alert) for alert in rows]


def _customer_facts(db: Session, customer: Customer) -> dict:
    profile = db.scalar(
        select(CustomerProfile).where(CustomerProfile.customer_id == customer.id)
    )
    names = names_by_id(db, {customer.manager_id})
    return {
        "customer_id": customer.id,
        "real_name": customer.real_name,
        "customer_level": customer.customer_level,
        "risk_level": profile.risk_level if profile is not None else None,
        "manager_name": names.get(customer.manager_id, "") if customer.manager_id else "",
    }


def _ensure_can_view(db: Session, employee: Employee, alert: RiskAlert) -> None:
    """客户经理只能看自己名下客户的预警，其他内部角色不受限。"""
    if not restrict_to_own_customers(employee):
        return
    if not is_under_management(db.get(Customer, alert.customer_id), employee):
        raise AppError(403, NOT_YOUR_CUSTOMER_MESSAGE)


def detail(db: Session, alert_id: int, *, employee: Employee) -> dict:
    """预警详情：一次拿全判断它需要的东西。"""
    alert = disposition.get_alert(db, alert_id)
    _ensure_can_view(db, employee, alert)

    customer = db.get(Customer, alert.customer_id)
    if customer is None:
        raise AppError(404, CUSTOMER_NOT_FOUND_MESSAGE)

    work_order = work_orders.find_by_alert(db, alert.id)
    names = names_by_id(
        db, {alert.handler_id, work_order.handler_id if work_order is not None else None}
    )
    return {
        **alerting.alert_response(alert),
        "customer_name": customer.real_name,
        # 来源标注：客户发起 / 内部补录，依据是关联交易有没有经办员工（Q22）。
        "source": alerting.alert_sources(db, [alert])[alert.id],
        # 处置人姓名而不是工号：「这条预警是谁放过的」要能直接读出来。
        "handled_by_name": names.get(alert.handler_id, "") if alert.handler_id else "",
        "customer": _customer_facts(db, customer),
        "transactions": _transactions(db, list(alert.transaction_ids or [])),
        "customer_history": _customer_history(
            db, customer_id=alert.customer_id, exclude_alert_id=alert.id
        ),
        "work_order": (
            work_orders.serialize(
                work_order, handler_name=names.get(work_order.handler_id, "")
            )
            if work_order is not None
            else None
        ),
    }
