"""交易事件落库、广播与预警生成。

一笔交易事件的处置顺序是固定的三步，改动顺序会破坏不变量：

1. **先事务性落库**。交易记录是事实，先落库才有后面的一切。
2. **再广播**。广播失败只记日志、不回滚（`event_bus.publish_safely`）——交易记录
   不能因为广播通道的问题而丢失，订阅方漏收可以按库里的事实补查。
3. **最后过规则引擎**。命中即产生预警，预警本身再广播一次。

阈值判断的任何环节都不经过模型：命中与否由 `evaluator` 的算子决定，这里只负责
把命中结果落成预警。

预警是**事实记录**：什么规则在什么交易上命中了，带等级与置信度。它的初始状态是
「未处理」——陈述「还没有人处置过」，不是工单流程里的任何节点；处置过程与状态
流转由预警派生的工单承载（另一个 slice）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Customer, CustomerProfile, Product, RiskAlert, Transaction
from app.event_bus import (
    EVENT_RISK_ALERT_RAISED,
    EVENT_TRANSACTION_SUBMITTED,
    SOURCE_RISK_MONITORING,
    Event,
    EventPublisher,
    publish_safely,
)
from app.exceptions import AppError
from app.risk_monitoring import service
from app.risk_monitoring.alert_status import ALERT_STATUS_OPEN
from app.risk_monitoring.context import CustomerSnapshot, MonitoringContext, RuleSpec, TransactionEvent
from app.risk_monitoring.evaluator import match_rules
from app.risk_monitoring.fields import OPPOSITE_TRANSACTION_TYPES
from app.risk_monitoring.grading import (
    alert_type_for,
    compute_confidence,
    grade_alert_level,
    render_trigger_detail,
)
from app.tracing import get_trace_id

logger = logging.getLogger("app.risk_monitoring")

# 申购与赎回取自字段层的反向配对表，它不是抄一遍类型清单：规则引擎认得的类型就是
# 这两个（`purchase_amount` / `redeem_amount` 按类型取值，快进快出按这两个方向配对），
# 将来加类型时配对表先变，这里的清单跟着变，不会漏。
TRANSFER = "转账"

# 转账是需求文档里点名的场景（「监测到 50 万大额转账」），但规则只建在金额上，没有
# 类型分支，因此可以收。其他类型在规则引擎里没有对应语义，收进来只会让一批规则永
# 不命中——静默漏报，所以挡在写入侧并当场报错。
TRANSACTION_TYPES: tuple[str, ...] = (*OPPOSITE_TRANSACTION_TYPES, TRANSFER)

TRANSACTION_STATUS_CONFIRMED = "已确认"

# 预警落库时的初始状态来自 `alert_status`：一个事实陈述（还没有人处置过），不是
# 工单流程节点。这里只写一次，离开它的两条路径（排除 / 升级）在
# `app.risk_monitoring.disposition`。

DAY_HOURS = 24

UNKNOWN_TRANSACTION_TYPE_MESSAGE = "不支持的交易类型"
NON_POSITIVE_AMOUNT_MESSAGE = "交易金额必须大于零"
CUSTOMER_NOT_FOUND_MESSAGE = "客户不存在"
PRODUCT_NOT_FOUND_MESSAGE = "产品不存在"
DUPLICATE_TRANSACTION_NO_MESSAGE = "交易流水号已存在"


def history_lookback_hours(rules: list[RuleSpec]) -> int:
    """求值要回溯多久的历史。

    取启用规则里最长的时间窗，且不少于一个自然日——同日累计类算子也读历史，
    一个都不能少，否则窗口内的笔数会凭空变少，漏报而不报错。
    """
    longest = max((rule.window_hours or 0 for rule in rules), default=0)
    return max(longest, DAY_HOURS)


def _to_event(transaction: Transaction) -> TransactionEvent:
    return TransactionEvent(
        transaction_id=transaction.id,
        customer_id=transaction.customer_id,
        product_id=transaction.product_id,
        transaction_type=transaction.transaction_type,
        amount=transaction.amount,
        occurred_at=transaction.create_time,
    )


def build_context(
    db: Session, transaction: Transaction, *, lookback_hours: int
) -> MonitoringContext:
    """把库里的事实拼成求值输入：本笔事件、同客户之前的事件、产品与客户画像。"""
    start = transaction.create_time - timedelta(hours=lookback_hours)
    history = db.scalars(
        select(Transaction)
        .where(
            Transaction.customer_id == transaction.customer_id,
            Transaction.id != transaction.id,
            Transaction.create_time >= start,
            Transaction.create_time <= transaction.create_time,
        )
        .order_by(Transaction.create_time.asc(), Transaction.id.asc())
    ).all()

    product = db.get(Product, transaction.product_id)
    profile = db.scalar(
        select(CustomerProfile).where(CustomerProfile.customer_id == transaction.customer_id)
    )

    return MonitoringContext(
        event=_to_event(transaction),
        history=tuple(_to_event(row) for row in history),
        product_risk_level=product.risk_level if product is not None else None,
        customer=CustomerSnapshot(
            risk_level=profile.risk_level if profile is not None else None,
            total_assets=profile.total_assets if profile is not None else None,
        ),
    )


def _customer_has_prior_alert(db: Session, *, customer_id: int, now: datetime) -> bool:
    """这位客户在本条预警之前是否已经被记录过预警。

    界线用显式传入的 `now`（本条预警的产生时刻），而不是本笔交易的 `create_time`：
    「历史预警记录」说的是本系统已经记下了什么，与交易发生在什么时候是两件事。
    回放一笔旧交易时，晚于它、但已经被记录下来的预警仍然算这家客户的既有记录——
    否则同一位客户的历史会在回放里凭空消失。

    边界放宽到下一秒，因为 `create_time` 是秒精度的列：MySQL 存小数秒时四舍五入，
    `.6` 秒会被存成下一秒，于是刚写下的那条可能比 `now` 还大零点几秒。用
    `create_time < now` 去比会把它排除在外——同一秒里接连发生的两笔交易于是被算成
    「没有历史」，多规则交叉的重度直接降成中度，而它恰恰是最该先看的那一条。
    本条预警此时还没有落库（`db.add` 在下面），所以放宽一秒不会把正在产生的这条
    算成自己的历史。
    """
    count = db.scalar(
        select(func.count())
        .select_from(RiskAlert)
        .where(
            RiskAlert.customer_id == customer_id,
            RiskAlert.create_time <= now + timedelta(seconds=1),
        )
    )
    return bool(count)


def _transaction_event(transaction: Transaction) -> Event:
    return Event(
        event_type=EVENT_TRANSACTION_SUBMITTED,
        source=SOURCE_RISK_MONITORING,
        payload={
            "transaction_id": transaction.id,
            "transaction_no": transaction.transaction_no,
            "customer_id": transaction.customer_id,
            "product_id": transaction.product_id,
            "transaction_type": transaction.transaction_type,
            "amount": format(transaction.amount, "f"),
            "occurred_at": transaction.create_time.isoformat(),
        },
        occurred_at=transaction.create_time,
        trace_id=get_trace_id(),
    )


def _alert_event(alert: RiskAlert) -> Event:
    """预警广播载荷：预警标识、客户标识、等级、命中规则标识（外加类型与置信度）。"""
    return Event(
        event_type=EVENT_RISK_ALERT_RAISED,
        source=SOURCE_RISK_MONITORING,
        payload={
            "alert_id": alert.id,
            "customer_id": alert.customer_id,
            "alert_level": alert.alert_level,
            "alert_type": alert.alert_type,
            "confidence": format(alert.confidence, "f"),
            "rule_codes": list(alert.rule_codes or []),
            "transaction_ids": list(alert.transaction_ids or []),
        },
        occurred_at=alert.create_time,
        trace_id=get_trace_id(),
    )


def create_alerts_for_transaction(
    db: Session,
    *,
    transaction: Transaction,
    publisher: EventPublisher,
    now: datetime,
) -> list[RiskAlert]:
    """对一笔已落库的交易过一遍规则引擎，命中即产生一条预警。

    一笔交易最多产生一条预警：它把该笔命中的规则都收在同一条记录里，因此分级看的
    是「这一笔命中了多少条」；否则同一笔交易会被拆成互不相关的多条预警。
    """
    rules = service.enabled_rule_specs(db)
    if not rules:
        return []

    context = build_context(db, transaction, lookback_hours=history_lookback_hours(rules))
    hits = match_rules(rules, context)
    if not hits:
        return []

    alert = RiskAlert(
        customer_id=transaction.customer_id,
        alert_type=alert_type_for(hits),
        alert_level=grade_alert_level(
            len(hits),
            has_prior_alert=_customer_has_prior_alert(
                db, customer_id=transaction.customer_id, now=now
            ),
        ),
        confidence=compute_confidence(hits),
        rule_codes=[hit.rule_code for hit in hits],
        trigger_detail=render_trigger_detail(hits),
        transaction_ids=[transaction.id],
        status=ALERT_STATUS_OPEN,
        handler_id=None,
        handle_result=None,
        create_time=now,
        update_time=now,
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)

    publish_safely(publisher, _alert_event(alert))
    return [alert]


def _require_transaction_type(transaction_type: str) -> str:
    if transaction_type not in TRANSACTION_TYPES:
        raise AppError(400, UNKNOWN_TRANSACTION_TYPE_MESSAGE)
    return transaction_type


def _require_customer(db: Session, customer_id: int) -> None:
    if db.get(Customer, customer_id) is None:
        raise AppError(404, CUSTOMER_NOT_FOUND_MESSAGE)


def _require_product(db: Session, product_id: int) -> None:
    if db.get(Product, product_id) is None:
        raise AppError(404, PRODUCT_NOT_FOUND_MESSAGE)


def _resolve_transaction_no(db: Session, provided: str | None, occurred_at: datetime) -> str:
    number = provided.strip() if provided and provided.strip() else (
        f"TX{occurred_at:%Y%m%d%H%M%S}{uuid4().hex[:6].upper()}"
    )
    exists = db.scalar(select(Transaction.id).where(Transaction.transaction_no == number))
    if exists is not None:
        raise AppError(409, DUPLICATE_TRANSACTION_NO_MESSAGE)
    return number


@dataclass(frozen=True)
class TransactionSubmission:
    """一笔待接收的交易事件。字段与 `fin_transaction` 的必填列一一对应。

    `shares` / `nav` / `fee` 风控用不到，但交易流水本身要它们——它同时是客户可见
    视图里的成交记录，缺了这三个数就是一笔查不清的流水。
    """

    customer_id: int
    product_id: int
    transaction_type: str
    amount: Decimal
    occurred_at: datetime
    shares: Decimal = Decimal("0")
    nav: Decimal = Decimal("0")
    fee: Decimal = Decimal("0")
    transaction_no: str | None = None


def submit_transaction_event(
    db: Session,
    *,
    publisher: EventPublisher,
    submission: TransactionSubmission,
    operator_id: int | None,
    now: datetime,
) -> tuple[Transaction, list[RiskAlert]]:
    """接收一笔交易事件：先落库，再广播，最后过规则引擎。

    返回落库后的交易与它产生的预警（可能为空）。
    """
    if submission.amount <= 0:
        raise AppError(400, NON_POSITIVE_AMOUNT_MESSAGE)
    _require_transaction_type(submission.transaction_type)
    _require_customer(db, submission.customer_id)
    _require_product(db, submission.product_id)
    number = _resolve_transaction_no(db, submission.transaction_no, submission.occurred_at)

    transaction = Transaction(
        transaction_no=number,
        customer_id=submission.customer_id,
        product_id=submission.product_id,
        transaction_type=submission.transaction_type,
        amount=submission.amount,
        shares=submission.shares,
        nav=submission.nav,
        fee=submission.fee,
        status=TRANSACTION_STATUS_CONFIRMED,
        operator_id=operator_id,
        create_time=submission.occurred_at,
    )
    # 第一步：事务性落库。广播与规则匹配都在它之后，且都不影响它的存在。
    db.add(transaction)
    db.commit()
    db.refresh(transaction)

    # 第二步：广播。失败只记日志，不回滚。
    publish_safely(publisher, _transaction_event(transaction))

    # 第三步：过规则引擎。
    alerts = create_alerts_for_transaction(
        db, transaction=transaction, publisher=publisher, now=now
    )
    return transaction, alerts


def transaction_response(transaction: Transaction) -> dict:
    return {
        "transaction_no": transaction.transaction_no,
        "customer_id": transaction.customer_id,
        "product_id": transaction.product_id,
        "transaction_type": transaction.transaction_type,
        "amount": format(transaction.amount, "f"),
        "status": transaction.status,
        "occurred_at": transaction.create_time.isoformat(),
    }


def alert_response(alert: RiskAlert) -> dict:
    return {
        "id": alert.id,
        "customer_id": alert.customer_id,
        "alert_type": alert.alert_type,
        "alert_level": alert.alert_level,
        "confidence": float(alert.confidence),
        "rule_codes": list(alert.rule_codes or []),
        "transaction_ids": list(alert.transaction_ids or []),
        "trigger_detail": alert.trigger_detail,
        "status": alert.status,
        # 处置留痕：还没处置时两列都为空，「未处理」是它们的搭档状态。
        "handler_id": alert.handler_id,
        "handle_result": alert.handle_result,
        "created_at": alert.create_time.isoformat(),
    }
