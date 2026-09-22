"""交易事件落库、广播与预警生成。

一笔交易事件的处置顺序是固定的三步，改动顺序会破坏不变量：

1. **先事务性落库**。交易记录是事实，先落库才有后面的一切。事实落在哪张表由有没有
   产品决定：申购、赎回与内部补录落在 `fin_transaction`，转账落在 `fin_transfer`
   （ADR-0019），充值落在 `fin_deposit`（ADR-0023）——后两者由受理侧写入、由这里提交。
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
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import degradation
from app.db.models import (
    Customer,
    CustomerProfile,
    Deposit,
    Product,
    RiskAlert,
    Transaction,
    Transfer,
)
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
    hit_evidence,
    render_trigger_detail,
)
from app.tracing import get_trace_id

logger = logging.getLogger("app.risk_monitoring")

# 与 `app.agent.config.RISK_MONITORING_CONFIG.name` 同一个取值，这里写字面量而不是
# 导入它：风控判定链路不许碰模型层（见 tests/test_risk_rule_evaluation 的守卫用例），
# 而 app.agent 是模型层的入口。两处取值的一致性由 tests/test_degradation_paths 固定。
AGENT_TYPE_RISK_MONITORING = "risk_monitoring"


def _publish_or_record(db: Session, publisher: EventPublisher, event: Event) -> None:
    """广播一个事件；失败只留降级痕迹并继续——核心链路的结果已经落库。

    `publish_safely` 负责「不抛异常」，这里负责「失败可统计」：广播是增强，但它
    有没有真的发出去，是事后要能回答的问题。
    """
    if publish_safely(publisher, event):
        return
    degradation.record(
        db,
        dependency=degradation.DEPENDENCY_EVENT_BUS,
        reason=degradation.REASON_UNAVAILABLE,
        agent_type=AGENT_TYPE_RISK_MONITORING,
        trace_id=get_trace_id(),
    )

# 申购与赎回取自字段层的反向配对表，它不是抄一遍类型清单：规则引擎认得的类型就是
# 这两个（`purchase_amount` / `redeem_amount` 按类型取值，快进快出按这两个方向配对），
# 将来加类型时配对表先变，这里的清单跟着变，不会漏。
TRANSFER = "转账"
DEPOSIT = "充值"

# 类型分支只活在 7 条规则里（R011–R014 按方向取值或配对、R016 产品维、R019 越级、
# R020 大额赎回），其余 13 条只建在金额、笔数与时段上（R001–R010、R015、R017、
# R018）。转账与充值没有产品，但金额、笔数与时段这些信号照常有意义，因此都收得下；
# 真正进不来的类型是规则引擎里没有任何对应语义的类型——收进来只会让一批规则永不命中
# （静默漏报），所以挡在写入侧并当场报错。
TRANSACTION_TYPES: tuple[str, ...] = (*OPPOSITE_TRANSACTION_TYPES, TRANSFER, DEPOSIT)

TRANSACTION_STATUS_CONFIRMED = "已确认"

# 预警来源的两个取值（Q22）：交易的来源**不加字段**，分辨依据是关联交易有没有经办
# 员工——客户自助发起的没有，内部补录的必带。这两个字面量是预警列表与详情上标注的
# 全部取值，别处不要再拼一遍。
SOURCE_CUSTOMER = "客户发起"
SOURCE_INTERNAL_BACKFILL = "内部补录"

# 预警落库时的初始状态来自 `alert_status`：一个事实陈述（还没有人处置过），不是
# 工单流程节点。这里只写一次，离开它的两条路径（排除 / 升级）在
# `app.risk_monitoring.disposition`。

DAY_HOURS = 24

UNKNOWN_TRANSACTION_TYPE_MESSAGE = "不支持的交易类型"
NON_POSITIVE_AMOUNT_MESSAGE = "交易金额必须大于零"
CUSTOMER_NOT_FOUND_MESSAGE = "客户不存在"
PRODUCT_NOT_FOUND_MESSAGE = "产品不存在"
DUPLICATE_TRANSACTION_NO_MESSAGE = "交易流水号已存在"
# 无产品的事件（转账与充值）必须带上已落库事实的标识：入海口不替它写 fin_transaction，
# 那个标识是它唯一能被广播与预警关联上的凭据。这是内部约定，不面向客户。
RECORDED_FACT_REQUIRED_MESSAGE = "交易事件缺少已落库事实的标识"


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


def _fin_transaction_id(event: TransactionEvent) -> int | None:
    """本笔事件在 `fin_transaction` 里的行标识；转账与充值没有那一行（ADR-0019/0023）。

    `TransactionEvent.transaction_id` 是「本笔事实在自己那张表里的标识」：有产品的
    交易落在 `fin_transaction`，转账落在 `fin_transfer`，充值落在 `fin_deposit`，三边的
    id 各自从 1 开始。预警的 `transaction_ids` 存的是前者，转账与充值因此不填它——混着
    填会让预警详情按 id 回查到另一笔毫不相干的交易，而那种错在界面上看起来完全正常。
    """
    return event.transaction_id if event.product_id is not None else None


def _transfer_event(transfer: Transfer) -> TransactionEvent:
    """一行转账也是一个交易事件：没有产品，类型固定为「转账」。"""
    return TransactionEvent(
        transaction_id=transfer.id,
        customer_id=transfer.customer_id,
        product_id=None,
        transaction_type=TRANSFER,
        amount=transfer.amount,
        occurred_at=transfer.create_time,
    )


def _deposit_event(deposit: Deposit) -> TransactionEvent:
    """一行充值也是一个交易事件：没有产品，类型固定为「充值」。"""
    return TransactionEvent(
        transaction_id=deposit.id,
        customer_id=deposit.customer_id,
        product_id=None,
        transaction_type=DEPOSIT,
        amount=deposit.amount,
        occurred_at=deposit.create_time,
    )


def _history_events(
    db: Session, *, event: TransactionEvent, start: datetime
) -> list[TransactionEvent]:
    """同客户、在本笔之前、回溯窗口内的事件，按发生时间升序。

    **三张流水表都要读**（ADR-0019/0023）：转账与充值不是 `fin_transaction` 的行，
    漏掉它们不会报错，只会让窗口与累计类规则少算几笔——那不是漏报某一条规则，是所有
    读历史的算子一起少算，而且从结果上完全看不出来。

    自身那一行按事件来自哪张表排除：三张表的 id 各自从 1 开始，拿一个去排除另一张表
    的行会误伤不相干的交易。有产品的事件来自 `fin_transaction`（`product_id` 非空），
    无产品的事件按类型分：转账来自 `fin_transfer`，充值来自 `fin_deposit`。

    已知的精度限制（既有的，不是这里引入的）：成交时间是秒精度列，带小数秒的时间会被
    四舍五入到下一秒，于是「同一秒里更早那一笔」有时不在历史里。人手动操作不会撞上，
    批量回放也不会——`_customer_has_prior_alert` 对同一个限制做了放宽，两处的口径
    不同是因为它们问的不是同一个问题（那个问「系统记下了什么」，这个问「钱动过几笔」）。
    """
    transaction_stmt = select(Transaction).where(
        Transaction.customer_id == event.customer_id,
        Transaction.create_time >= start,
        Transaction.create_time <= event.occurred_at,
    )
    if event.product_id is not None:
        transaction_stmt = transaction_stmt.where(Transaction.id != event.transaction_id)

    transfer_stmt = select(Transfer).where(
        Transfer.customer_id == event.customer_id,
        Transfer.create_time >= start,
        Transfer.create_time <= event.occurred_at,
    )
    if event.transaction_type == TRANSFER:
        transfer_stmt = transfer_stmt.where(Transfer.id != event.transaction_id)

    deposit_stmt = select(Deposit).where(
        Deposit.customer_id == event.customer_id,
        Deposit.create_time >= start,
        Deposit.create_time <= event.occurred_at,
    )
    if event.transaction_type == DEPOSIT:
        deposit_stmt = deposit_stmt.where(Deposit.id != event.transaction_id)

    events = [_to_event(row) for row in db.scalars(transaction_stmt).all()]
    events.extend(_transfer_event(row) for row in db.scalars(transfer_stmt).all())
    events.extend(_deposit_event(row) for row in db.scalars(deposit_stmt).all())
    # 时间相同的两笔先后无所谓（间隔为零），因此只按时间排；稳定排序让结果可复现。
    events.sort(key=lambda item: item.occurred_at)
    return events


def build_context(
    db: Session, event: TransactionEvent, *, lookback_hours: int
) -> MonitoringContext:
    """把库里的事实拼成求值输入：本笔事件、同客户之前的事件、产品与客户画像。"""
    start = event.occurred_at - timedelta(hours=lookback_hours)
    product = db.get(Product, event.product_id) if event.product_id is not None else None
    profile = db.scalar(
        select(CustomerProfile).where(CustomerProfile.customer_id == event.customer_id)
    )

    return MonitoringContext(
        event=event,
        history=tuple(_history_events(db, event=event, start=start)),
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


def _transaction_event(
    *,
    transaction_id: int,
    transaction_no: str,
    customer_id: int,
    product_id: int | None,
    transaction_type: str,
    amount: Decimal,
    occurred_at: datetime,
) -> Event:
    """交易事件的广播载荷。有产品的交易、转账与充值共用一份形状，不各拼一遍。

    转账与充值的 `product_id` 为空（ADR-0019/0023）；订阅方读的是载荷里有的那几样，
    空值不会让谁少收到事件。
    """
    return Event(
        event_type=EVENT_TRANSACTION_SUBMITTED,
        source=SOURCE_RISK_MONITORING,
        payload={
            "transaction_id": transaction_id,
            "transaction_no": transaction_no,
            "customer_id": customer_id,
            "product_id": product_id,
            "transaction_type": transaction_type,
            "amount": format(amount, "f"),
            "occurred_at": occurred_at.isoformat(),
        },
        occurred_at=occurred_at,
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


def create_alerts_for_event(
    db: Session,
    *,
    event: TransactionEvent,
    publisher: EventPublisher,
    now: datetime,
) -> list[RiskAlert]:
    """对一笔已落库的交易事件过一遍规则引擎，命中即产生一条预警。

    一笔交易最多产生一条预警：它把该笔命中的规则都收在同一条记录里，因此分级看的
    是「这一笔命中了多少条」；否则同一笔交易会被拆成互不相关的多条预警。
    """
    rules = service.enabled_rule_specs(db)
    if not rules:
        return []

    context = build_context(db, event, lookback_hours=history_lookback_hours(rules))
    hits = match_rules(rules, context)
    if not hits:
        return []

    fin_transaction_id = _fin_transaction_id(event)
    alert = RiskAlert(
        customer_id=event.customer_id,
        alert_type=alert_type_for(hits),
        alert_level=grade_alert_level(
            len(hits),
            has_prior_alert=_customer_has_prior_alert(
                db, customer_id=event.customer_id, now=now
            ),
        ),
        confidence=compute_confidence(hits),
        rule_codes=[hit.rule_code for hit in hits],
        # 依据在命中这一刻固化：阈值会被调整（`fin_risk_rule_change` 记着谁改的），
        # 展示时回查规则等于用今天的口径解释过去的预警。
        rule_hits=[hit_evidence(hit) for hit in hits],
        trigger_detail=render_trigger_detail(hits),
        # 关联交易是 `fin_transaction` 的标识；转账没有那一行（ADR-0019），
        # 因此这一列为空，金额与类型仍在命中依据里。
        transaction_ids=[fin_transaction_id] if fin_transaction_id is not None else [],
        status=ALERT_STATUS_OPEN,
        handler_id=None,
        handle_result=None,
        create_time=now,
        update_time=now,
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)

    _publish_or_record(db, publisher, _alert_event(alert))
    return [alert]


def _require_transaction_type(transaction_type: str) -> str:
    if transaction_type not in TRANSACTION_TYPES:
        raise AppError(400, UNKNOWN_TRANSACTION_TYPE_MESSAGE)
    return transaction_type


def _require_customer(db: Session, customer_id: int) -> None:
    if db.get(Customer, customer_id) is None:
        raise AppError(404, CUSTOMER_NOT_FOUND_MESSAGE)


def _require_product(db: Session, product_id: int | None) -> None:
    """有产品才要求它存在。

    转账没有产品（ADR-0019），它的事件里 `product_id` 为空。风控的交易事件模型本来
    就不假设交易一定有产品（`TransactionEvent.product_id` 可空），入海口因此不能对
    无产品的事件报「产品不存在」——那会把转账挡在监测之外。
    """
    if product_id is None:
        return
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

    `product_id` 可空：转账与充值没有产品（ADR-0019/0023）。没有产品时事实不落在
    `fin_transaction` 里，因此由受理侧传入 `transaction_id` 与 `transaction_no`
    ——「先事务性落库」这一步仍然发生，只是那一行在转账或充值自己的表里。
    """

    customer_id: int
    product_id: int | None
    transaction_type: str
    amount: Decimal
    occurred_at: datetime
    shares: Decimal = Decimal("0")
    nav: Decimal = Decimal("0")
    fee: Decimal = Decimal("0")
    transaction_no: str | None = None
    # 已经落库的事实的标识，只在没有产品时由受理侧传入（转账、充值）。
    transaction_id: int | None = None


def _submit_recorded_fact(
    db: Session,
    *,
    publisher: EventPublisher,
    submission: TransactionSubmission,
    now: datetime,
) -> tuple[None, list[RiskAlert]]:
    """转账与充值：事实已经由受理侧写在自己的表里，这里只提交它、广播、过规则引擎。

    「先事务性落库」这一步不能省——受理侧把事实行与可用余额的变动写在同一个会话里，
    由这里一次提交，广播与规则匹配因此都发生在事实落库之后（进入海口本来就窄，
    业务校验不在这里，ADR-0018）。
    """
    if submission.transaction_id is None or not submission.transaction_no:
        raise AppError(400, RECORDED_FACT_REQUIRED_MESSAGE)
    # 第一步：事务性落库。
    db.commit()

    event = TransactionEvent(
        transaction_id=submission.transaction_id,
        customer_id=submission.customer_id,
        product_id=None,
        transaction_type=submission.transaction_type,
        amount=submission.amount,
        occurred_at=submission.occurred_at,
    )

    # 第二步：广播。失败只记日志与降级留痕，不回滚。
    _publish_or_record(
        db,
        publisher,
        _transaction_event(
            transaction_id=submission.transaction_id,
            transaction_no=submission.transaction_no,
            customer_id=submission.customer_id,
            product_id=None,
            transaction_type=submission.transaction_type,
            amount=submission.amount,
            occurred_at=submission.occurred_at,
        ),
    )

    # 第三步：过规则引擎。
    alerts = create_alerts_for_event(db, event=event, publisher=publisher, now=now)
    return None, alerts


def submit_transaction_event(
    db: Session,
    *,
    publisher: EventPublisher,
    submission: TransactionSubmission,
    operator_id: int | None,
    now: datetime,
) -> tuple[Transaction | None, list[RiskAlert]]:
    """接收一笔交易事件：先落库，再广播，最后过规则引擎。

    有产品的交易（申购、赎回、内部补录）由这里落 `fin_transaction` 并返回它；转账
    与充值没有产品，事实分别落在 `fin_transfer` 与 `fin_deposit` 里，这里只提交、
    广播、过规则引擎，返回的交易为 `None`。各条路径的先后顺序完全一样，因为风控的
    输入是既成事实而不是它的载体。
    """
    if submission.amount <= 0:
        raise AppError(400, NON_POSITIVE_AMOUNT_MESSAGE)
    _require_transaction_type(submission.transaction_type)
    _require_customer(db, submission.customer_id)
    _require_product(db, submission.product_id)

    if submission.product_id is None:
        return _submit_recorded_fact(db, publisher=publisher, submission=submission, now=now)

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

    # 第二步：广播。失败只记日志与降级留痕，不回滚。
    _publish_or_record(
        db,
        publisher,
        _transaction_event(
            transaction_id=transaction.id,
            transaction_no=transaction.transaction_no,
            customer_id=transaction.customer_id,
            product_id=transaction.product_id,
            transaction_type=transaction.transaction_type,
            amount=transaction.amount,
            occurred_at=transaction.create_time,
        ),
    )

    # 第三步：过规则引擎。
    alerts = create_alerts_for_event(
        db, event=_to_event(transaction), publisher=publisher, now=now
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


def alert_sources(db: Session, alerts: Sequence[RiskAlert]) -> dict[int, str]:
    """这批预警各自的来源：客户发起 / 内部补录。

    依据是**关联交易有没有经办员工**（Q22），不新增字段：

    - 关联交易里有经办员工 → 内部补录；
    - 关联交易都没有经办员工 → 客户发起；
    - 关联交易为空 → 客户发起。转账与充值没有 `fin_transaction` 那一行（ADR-0019/0023），
      而它们只从客户侧的受理进来——内部补录那条路必带产品、必然落在
      `fin_transaction` 里，所以这个兜底今天是对的。

    一次查完这批交易而不是逐条查：列表页每一行都要标来源，按行查就是 N 次往返。
    关联的交易已不存在时按客户发起处理：那一行都没了，没有别的依据可读。
    """
    transaction_ids = sorted(
        {transaction_id for alert in alerts for transaction_id in (alert.transaction_ids or [])}
    )
    operators: dict[int, int | None] = {}
    if transaction_ids:
        operators = {
            int(row_id): operator_id
            for row_id, operator_id in db.execute(
                select(Transaction.id, Transaction.operator_id).where(
                    Transaction.id.in_(transaction_ids)
                )
            ).all()
        }
    sources: dict[int, str] = {}
    for alert in alerts:
        backfilled = any(
            operators.get(transaction_id) is not None
            for transaction_id in (alert.transaction_ids or [])
        )
        sources[alert.id] = SOURCE_INTERNAL_BACKFILL if backfilled else SOURCE_CUSTOMER
    return sources


def alert_core(alert: RiskAlert) -> dict:
    """预警自身的那组事实字段。

    列表行、详情与「这位客户的历史预警」说的是同一条预警的同一组事实，形状从这里
    出一份：各拼一遍的话，将来加一个字段时总有一个视图会漏掉它，而漏掉的那个视图
    看起来仍然是「正常」的。
    """
    return {
        "id": alert.id,
        "customer_id": alert.customer_id,
        "alert_type": alert.alert_type,
        "alert_level": alert.alert_level,
        "confidence": float(alert.confidence),
        "rule_codes": list(alert.rule_codes or []),
        "transaction_ids": list(alert.transaction_ids or []),
        "status": alert.status,
        "created_at": alert.create_time.isoformat(),
    }


def alert_response(alert: RiskAlert) -> dict:
    return {
        **alert_core(alert),
        "rule_hits": list(alert.rule_hits or []),
        "trigger_detail": alert.trigger_detail,
        # 处置留痕：还没处置时两列都为空，「未处理」是它们的搭档状态。
        "handler_id": alert.handler_id,
        "handle_result": alert.handle_result,
    }
