"""工单：处置某一事项的流程载体（CONTEXT「工单」）。

工单不是预警的状态字段。预警陈述「什么被触发了」，处置过程由它派生的工单承载：
受理人、状态、处置结论，以及每一次流转的处置人与理由。

三条不变量在这里落地：

1. **一条预警最多派生一张工单**。派生入口先查一次给出明确的错误，数据库上的唯一
   约束是最后一道——两个并发请求只有一个能落库，另一个撞上约束后翻译成同一个错误。
2. **每次状态流转都要求非空理由**，并把处置人、时间与理由写进只追加的
   `biz_work_order_transition`。建单也写一条（`from_status` 为空），于是工单的每一个
   状态都有出处，不存在凭空出现的状态。
3. **生命周期是一条单向链**：`待处理 → 处理中 → 已完成 | 已关闭`。跳步与回头都被
   拒绝——「谁把它推到了这个状态」才查得清。

工单也能来自预警之外的源头（客户投诉、转人工）：这类工单不带来源预警，也不受
「一条预警一张工单」的约束（留空的列在唯一索引里可以有任意多个）。但来源类型不能
自称「预警处置」——那会绕开唯一约束，让一条预警被反复处置。

工单与预警的生命周期不合并：工单办结不会关掉预警，预警的关闭只能由人做出并留下
理由（`app.risk_monitoring.disposition`）。
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.roles import ACCOUNT_MANAGER
from app.customer_scope import is_under_management, restrict_to_own_customers
from app.db.models import Customer, Employee, RiskAlert, WorkOrder, WorkOrderTransition
from app.employees import names_by_id
from app.exceptions import AppError
from app.pagination import PageParams, count_matching, paginated_response
from app.risk_monitoring.alert_status import ALERT_STATUS_OPEN
from app.risk_monitoring.grading import LEVEL_LIGHT, LEVEL_MODERATE, LEVEL_SEVERE

STATUS_PENDING = "待处理"
STATUS_IN_PROGRESS = "处理中"
STATUS_COMPLETED = "已完成"
STATUS_CLOSED = "已关闭"

# 「能不能从 A 到 B」是这张工单的全部流程定义，写成表而不是一串 if，让人一眼看到
# 全貌：终端状态没有任何下一步，这是「办结之后不能再流转」的来源。
NEXT_STATUSES: dict[str, tuple[str, ...]] = {
    STATUS_PENDING: (STATUS_IN_PROGRESS,),
    STATUS_IN_PROGRESS: (STATUS_COMPLETED, STATUS_CLOSED),
    STATUS_COMPLETED: (),
    STATUS_CLOSED: (),
}

# 需求文档给这个来源起的名字是「可疑交易上报」。本 slice 把监管报送明确排除在外
# （spec 的 Out of Scope），这张工单的职责是处置预警、不是对外报送，所以按实际职责
# 命名——名字一旦承诺了报送，就会有人以为报送那一步已经在系统里了。
ORDER_TYPE_ALERT = "预警处置"
ORDER_TYPE_COMPLAINT = "客户投诉"
ORDER_TYPE_TRANSFER = "转人工"

# 预警之外的来源。客户投诉与转人工总是由人建单，所以只有这两种；「预警处置」只能
# 由预警派生，从建单入口进来会绕开「一条预警一张工单」。
EXTERNAL_ORDER_TYPES: tuple[str, ...] = (ORDER_TYPE_COMPLAINT, ORDER_TYPE_TRANSFER)

# 优先级取需求文档为 `biz_work_order.priority` 定下的三个值，不另造一套刻度。
PRIORITY_ROUTINE = "普通"
PRIORITY_URGENT = "紧急"
PRIORITY_CRITICAL = "特急"

# 等级到优先级的映射是代码：等级已经由「命中几条规则 + 有没有历史预警」算过一遍
# （`app.risk_monitoring.grading`），再让人对着工单选一次优先级，只会让两者对不上。
# 等级字面量引 `grading` 的常量，不在这里重抄一份。
PRIORITY_BY_ALERT_LEVEL: dict[str, str] = {
    LEVEL_SEVERE: PRIORITY_CRITICAL,
    LEVEL_MODERATE: PRIORITY_URGENT,
    LEVEL_LIGHT: PRIORITY_ROUTINE,
}

# 预期之外的等级走普通：宁可排在后头，也不因为一个没见过的字面量而报错丢单。
PRIORITY_FALLBACK = PRIORITY_ROUTINE

# 工单的提交人只可能是内部员工：客户与内部员工是两个身份域，一个域签发的凭证在
# 另一个域内一律无效（ADR-0004）。
IDENTITY_INTERNAL = "internal"

WORK_ORDER_NOT_FOUND_MESSAGE = "工单不存在"
ALERT_NOT_FOUND_MESSAGE = "预警不存在"
REASON_REQUIRED_MESSAGE = "流转理由不能为空"
CONCLUSION_REQUIRED_MESSAGE = "处置结论不能为空"
ALERT_ALREADY_HAS_WORK_ORDER_MESSAGE = "该预警已派生工单"
ALERT_ALREADY_HANDLED_MESSAGE = "该预警已处置，不能派生工单"
UNSUPPORTED_ORDER_TYPE_MESSAGE = "工单来源只支持客户投诉或转人工"
CUSTOMER_NOT_FOUND_MESSAGE = "客户不存在"
TRANSITION_NOT_ALLOWED_MESSAGE = "工单当前状态不允许该流转"
NOT_YOUR_CUSTOMER_MESSAGE = "该工单不在你名下客户的范围内，无权查看"


def _require_reason(reason: str | None) -> str:
    """流转理由必须非空。空白字符不算理由——「留个空格」与「没填」是一回事。"""
    if not reason or not reason.strip():
        raise AppError(400, REASON_REQUIRED_MESSAGE)
    return reason.strip()


def get_work_order(db: Session, work_order_id: int) -> WorkOrder:
    work_order = db.get(WorkOrder, work_order_id)
    if work_order is None:
        raise AppError(404, WORK_ORDER_NOT_FOUND_MESSAGE)
    return work_order


def find_by_alert(db: Session, alert_id: int) -> WorkOrder | None:
    return db.scalar(select(WorkOrder).where(WorkOrder.source_alert_id == alert_id))


def derive_from_alert(
    db: Session,
    *,
    alert_id: int,
    employee: Employee,
    reason: str | None,
    now: datetime,
) -> WorkOrder:
    """从一条预警派生工单：处置过程从此有了载体与责任人。

    已排除或已升级的预警不再派生工单——处置结论已经由人做出了，再开一张工单等于
    让同一个事实被处置两次。
    """
    checked_reason = _require_reason(reason)
    alert = db.get(RiskAlert, alert_id)
    if alert is None:
        raise AppError(404, ALERT_NOT_FOUND_MESSAGE)
    if alert.status != ALERT_STATUS_OPEN:
        raise AppError(409, ALERT_ALREADY_HANDLED_MESSAGE)
    if find_by_alert(db, alert_id) is not None:
        raise AppError(409, ALERT_ALREADY_HAS_WORK_ORDER_MESSAGE)

    work_order = _new_work_order(
        order_type=ORDER_TYPE_ALERT,
        customer_id=alert.customer_id,
        source_alert_id=alert.id,
        employee=employee,
        reason=checked_reason,
        priority=PRIORITY_BY_ALERT_LEVEL.get(alert.alert_level, PRIORITY_FALLBACK),
        # 预警命中结果的快照：工单详情不必回查预警就能说明「为什么会有这张单」。
        biz_content={
            "alert_level": alert.alert_level,
            "alert_type": alert.alert_type,
            "rule_codes": list(alert.rule_codes or []),
        },
        now=now,
    )
    return _insert(db, work_order, employee=employee, reason=checked_reason, now=now)


def create_external(
    db: Session,
    *,
    order_type: str,
    customer_id: int | None,
    employee: Employee,
    reason: str | None,
    now: datetime,
) -> WorkOrder:
    """建一张来自预警之外源头的工单（客户投诉、转人工）。"""
    if order_type not in EXTERNAL_ORDER_TYPES:
        raise AppError(400, UNSUPPORTED_ORDER_TYPE_MESSAGE)
    checked_reason = _require_reason(reason)
    if customer_id is not None and db.get(Customer, customer_id) is None:
        raise AppError(404, CUSTOMER_NOT_FOUND_MESSAGE)

    work_order = _new_work_order(
        order_type=order_type,
        customer_id=customer_id,
        source_alert_id=None,
        employee=employee,
        reason=checked_reason,
        priority=PRIORITY_FALLBACK,
        # 诉求原文留在这里：工单行上的「最近一次理由」会被后续流转覆盖，而「当初是
        # 因为什么建的这张单」不该被覆盖掉。
        biz_content={"description": checked_reason},
        now=now,
    )
    return _insert(db, work_order, employee=employee, reason=checked_reason, now=now)


def accept(
    db: Session,
    *,
    work_order_id: int,
    employee: Employee,
    reason: str | None,
    now: datetime,
) -> WorkOrder:
    """接单：待处理 → 处理中。

    受理人不变，变的是状态：受理人是责任人，处置人是这一次流转的操作人，两者都
    留痕。同组的风控专员可以接着别人的工单往下走，不会因此换掉责任人。
    """
    return _transition(
        db,
        work_order_id=work_order_id,
        to_status=STATUS_IN_PROGRESS,
        employee=employee,
        reason=reason,
        conclusion=None,
        require_conclusion=False,
        now=now,
    )


def complete(
    db: Session,
    *,
    work_order_id: int,
    employee: Employee,
    reason: str | None,
    conclusion: str | None,
    now: datetime,
) -> WorkOrder:
    """办结：处理中 → 已完成。处置结论是这个状态必须留下的东西，所以要求非空。"""
    return _transition(
        db,
        work_order_id=work_order_id,
        to_status=STATUS_COMPLETED,
        employee=employee,
        reason=reason,
        conclusion=conclusion,
        require_conclusion=True,
        now=now,
    )


def close(
    db: Session,
    *,
    work_order_id: int,
    employee: Employee,
    reason: str | None,
    conclusion: str | None,
    now: datetime,
) -> WorkOrder:
    """关闭：处理中 → 已关闭。

    终止的理由必须写清（「为什么这张单不做了」），但不要求一份处置结论——不是每张
    工单都以「办成了」结束，销户、重复建单这类终止本来就没有结论可写。填了结论
    也照样记下来。
    """
    return _transition(
        db,
        work_order_id=work_order_id,
        to_status=STATUS_CLOSED,
        employee=employee,
        reason=reason,
        conclusion=conclusion,
        require_conclusion=False,
        now=now,
    )


def list_work_orders(
    db: Session,
    *,
    employee: Employee,
    page: PageParams,
    status: str | None = None,
    alert_id: int | None = None,
    customer_id: int | None = None,
) -> dict:
    """工单列表的一页，按建单时间倒序。

    筛选条件都是可选的事实字段；可见范围按角色收紧：**客户经理只看得到自己名下客户
    的工单**，其他内部角色不受限——这与审核流的查看权限是同一口径
    （`app.advisory.access`）。写操作才收紧到风控专员。

    `total` 由同一条查询派生（`count_matching`），条件只写一遍：另写一条 count 把条件
    抄第二遍，漂移的表现是「共 N 条」与翻到底能看到的条数对不上，而且两个数字都像是
    真的。排序键是 `create_time` 倒序 + `id` 兜底：建单时间是秒精度，同一秒建的两张
    单若不分先后，翻页时会在两页之间来回跳。
    """
    conditions = []
    if employee.employee_role == ACCOUNT_MANAGER:
        # 内连接顺带把没有关联客户的工单挡在外面：那本来就不是「名下客户」的业务。
        conditions.append(Customer.manager_id == employee.id)
    if status is not None:
        conditions.append(WorkOrder.status == status)
    if alert_id is not None:
        conditions.append(WorkOrder.source_alert_id == alert_id)
    if customer_id is not None:
        conditions.append(WorkOrder.customer_id == customer_id)

    base = select(WorkOrder, Employee.real_name).join(
        Employee, Employee.id == WorkOrder.handler_id, isouter=True
    )
    if employee.employee_role == ACCOUNT_MANAGER:
        base = base.join(Customer, Customer.id == WorkOrder.customer_id)
    base = base.where(*conditions)

    total = count_matching(db, base)
    rows = db.execute(
        base.order_by(WorkOrder.create_time.desc(), WorkOrder.id.desc())
        .offset(page.offset)
        .limit(page.page_size)
    ).all()
    items = [serialize(work_order, handler_name=name or "") for work_order, name in rows]
    return paginated_response(items, total=total, params=page)


def detail(db: Session, work_order_id: int, *, employee: Employee) -> dict:
    """工单详情：连同它的流转留痕一起给出，处置页一次拿全。"""
    work_order = get_work_order(db, work_order_id)
    _ensure_can_view(db, employee, work_order)
    records = list(
        db.scalars(
            select(WorkOrderTransition)
            .where(WorkOrderTransition.work_order_id == work_order_id)
            .order_by(WorkOrderTransition.id.asc())
        ).all()
    )
    names = names_by_id(db, {work_order.handler_id, *(row.handler_id for row in records)})
    handler_name = names.get(work_order.handler_id, "") if work_order.handler_id else ""
    return {
        **serialize(work_order, handler_name=handler_name),
        "transitions": [
            serialize_transition(record, handler_name=names.get(record.handler_id, ""))
            for record in records
        ],
    }


def serialize(work_order: WorkOrder, *, handler_name: str = "") -> dict:
    return {
        "id": work_order.id,
        "work_order_no": work_order.work_order_no,
        "order_type": work_order.order_type,
        "sub_type": work_order.sub_type,
        # 对外叫 alert_id：调用方关心的是「它来自哪条预警」，「source_」是实现细节。
        "alert_id": work_order.source_alert_id,
        "customer_id": work_order.customer_id,
        "handler_id": work_order.handler_id,
        "handler_name": handler_name,
        "status": work_order.status,
        "current_node": work_order.current_node,
        "priority": work_order.priority,
        "biz_content": work_order.biz_content,
        "handle_reason": work_order.handle_reason,
        "handle_result": work_order.handle_result,
        "created_at": work_order.create_time.isoformat(),
        "updated_at": work_order.update_time.isoformat(),
    }


def serialize_transition(record: WorkOrderTransition, *, handler_name: str = "") -> dict:
    return {
        "from_status": record.from_status,
        "to_status": record.to_status,
        "handler_id": record.handler_id,
        "handler_name": handler_name,
        "reason": record.reason,
        "handled_at": record.handled_at.isoformat(),
    }


def _new_work_order(
    *,
    order_type: str,
    customer_id: int | None,
    source_alert_id: int | None,
    employee: Employee,
    reason: str,
    priority: str,
    biz_content: dict,
    now: datetime,
) -> WorkOrder:
    return WorkOrder(
        work_order_no=_new_number(now),
        order_type=order_type,
        sub_type=None,
        source_alert_id=source_alert_id,
        customer_id=customer_id,
        submitter_identity=IDENTITY_INTERNAL,
        submitter_id=employee.id,
        # 受理人在建单时即确定（派生人 / 建单人就是责任人）。接单这个动作只把状态推进
        # 到「处理中」，不改变责任人——否则一次接单就能悄悄换掉负责的人。
        handler_id=employee.id,
        current_node=STATUS_PENDING,
        priority=priority,
        status=STATUS_PENDING,
        biz_content=biz_content,
        handle_reason=reason,
        handle_result=None,
        create_time=now,
        update_time=now,
    )


def _new_number(now: datetime) -> str:
    """工单编号：时间前缀便于人读，随机后缀负责唯一。"""
    return f"WO{now:%Y%m%d%H%M%S}{uuid4().hex[:6].upper()}"


def _insert(
    db: Session,
    work_order: WorkOrder,
    *,
    employee: Employee,
    reason: str,
    now: datetime,
) -> WorkOrder:
    db.add(work_order)
    try:
        # 唯一约束在 flush 时才生效，所以先把工单写下去再挂留痕——留痕要它的主键。
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        # 只有从预警派生的这条路径上才有「一条预警一张工单」这个约束：并发派生时
        # 先查后写会双穿，这里接住约束给出的答案，换成同一个明确错误。别的约束
        # （比如工单编号撞车）不该被翻译成这句话，原样抛出去。
        if work_order.source_alert_id is None:
            raise
        raise AppError(409, ALERT_ALREADY_HAS_WORK_ORDER_MESSAGE) from exc

    db.add(_transition_row(work_order, from_status=None, employee=employee, reason=reason, now=now))
    db.commit()
    db.refresh(work_order)
    return work_order


def _ensure_can_view(db: Session, employee: Employee, work_order: WorkOrder) -> None:
    """客户经理只能看自己名下客户的工单，其他内部角色不受限。"""
    if not restrict_to_own_customers(employee):
        return
    customer = db.get(Customer, work_order.customer_id) if work_order.customer_id else None
    if not is_under_management(customer, employee):
        raise AppError(403, NOT_YOUR_CUSTOMER_MESSAGE)


def _transition(
    db: Session,
    *,
    work_order_id: int,
    to_status: str,
    employee: Employee,
    reason: str | None,
    conclusion: str | None,
    require_conclusion: bool,
    now: datetime,
) -> WorkOrder:
    checked_reason = _require_reason(reason)
    checked_conclusion = _checked_conclusion(conclusion, required=require_conclusion)

    work_order = get_work_order(db, work_order_id)
    # 没见过的状态视为无处可去：库里被塞进一个流程之外的状态时，宁可拒绝流转
    # 也不猜它该往哪走。
    if to_status not in NEXT_STATUSES.get(work_order.status, ()):
        raise AppError(409, TRANSITION_NOT_ALLOWED_MESSAGE)

    from_status = work_order.status
    work_order.status = to_status
    work_order.current_node = to_status
    work_order.handle_reason = checked_reason
    if checked_conclusion is not None:
        work_order.handle_result = checked_conclusion
    work_order.update_time = now
    db.add(
        _transition_row(
            work_order,
            from_status=from_status,
            employee=employee,
            reason=checked_reason,
            now=now,
        )
    )
    db.commit()
    db.refresh(work_order)
    return work_order


def _transition_row(
    work_order: WorkOrder,
    *,
    from_status: str | None,
    employee: Employee,
    reason: str,
    now: datetime,
) -> WorkOrderTransition:
    return WorkOrderTransition(
        work_order_id=work_order.id,
        from_status=from_status,
        to_status=work_order.status,
        handler_id=employee.id,
        reason=reason,
        handled_at=now,
    )


def _checked_conclusion(conclusion: str | None, *, required: bool) -> str | None:
    if not conclusion or not conclusion.strip():
        if required:
            raise AppError(400, CONCLUSION_REQUIRED_MESSAGE)
        return None
    return conclusion.strip()
